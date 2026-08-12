"""Durable aggregate budget enforcement for RuntimePlan execution."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .json_codec import dumps, loads
from .repositories import ConflictError, new_id
from .runtime_governance_models import (
    RuntimeBudgetConsumptionRow,
    RuntimeBudgetLedgerRow,
    RuntimeBudgetTaskUsageRow,
)
from .task_runtime_extensions import AGENT_PLAN_KIND
from .task_runtime_models import RuntimePlanRow, RuntimeTaskRow


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _positive_limit(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, number)


class RuntimeBudgetRepositoryMixin:
    def _ensure_ledger(self, plan_id: str) -> RuntimeBudgetLedgerRow:
        row = self.session.get(RuntimeBudgetLedgerRow, plan_id)
        if row is not None:
            return row
        now = time.time()
        try:
            with self.session.begin_nested():
                self.session.execute(
                    insert(RuntimeBudgetLedgerRow).values(
                        plan_id=plan_id,
                        prompt_tokens=0,
                        completion_tokens=0,
                        tool_calls=0,
                        cost_microunits=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            self.session.expire_all()
        row = self.session.get(RuntimeBudgetLedgerRow, plan_id)
        if row is None:
            raise ConflictError("runtime budget ledger could not be created")
        return row

    def _sync_plan_usage(
        self,
        plan: RuntimePlanRow,
        ledger: RuntimeBudgetLedgerRow,
    ) -> None:
        plan.usage_json = dumps(
            {
                "prompt_tokens": int(ledger.prompt_tokens),
                "completion_tokens": int(ledger.completion_tokens),
                "total_tokens": int(
                    ledger.prompt_tokens + ledger.completion_tokens
                ),
                "tool_calls": int(ledger.tool_calls),
                "cost_microunits": int(ledger.cost_microunits),
            }
        )
        plan.updated_at = time.time()
        self.session.flush()

    def _budget_violation(
        self,
        plan: RuntimePlanRow,
        ledger: RuntimeBudgetLedgerRow,
        *,
        now: float,
        include_tool_limit: bool,
        strict_current: bool,
    ) -> dict[str, Any] | None:
        budget = loads(plan.budget_json, {})
        prompt = int(ledger.prompt_tokens)
        completion = int(ledger.completion_tokens)
        total = prompt + completion
        tool_calls = int(ledger.tool_calls)
        started_at = float(plan.started_at or plan.created_at or now)
        wall_seconds = max(0.0, now - started_at)

        checks = [
            ("max_wall_seconds", wall_seconds),
            ("max_prompt_tokens", prompt),
            ("max_completion_tokens", completion),
            ("max_total_tokens", total),
        ]
        if include_tool_limit:
            checks.append(("max_tool_calls", tool_calls))
        for dimension, actual in checks:
            limit = _positive_limit(budget.get(dimension))
            if limit is None:
                continue
            exceeded = actual >= limit if strict_current else actual > limit
            if exceeded:
                return {
                    "dimension": dimension,
                    "limit": limit,
                    "actual": actual,
                    "message": (
                        f"runtime budget exceeded: {dimension} "
                        f"{actual:g}/{limit:g}"
                    ),
                }
        return None

    def budget_state(
        self,
        plan_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        plan = self._plan_row(plan_id)
        ledger = self._ensure_ledger(plan_id)
        checked_at = time.time() if now is None else float(now)
        budget = loads(plan.budget_json, {})
        prompt = int(ledger.prompt_tokens)
        completion = int(ledger.completion_tokens)
        started_at = float(plan.started_at or plan.created_at or checked_at)
        return {
            "plan_id": plan_id,
            "budget": budget,
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "tool_calls": int(ledger.tool_calls),
                "cost_microunits": int(ledger.cost_microunits),
                "wall_seconds": max(0.0, checked_at - started_at),
            },
            "violation": self._budget_violation(
                plan,
                ledger,
                now=checked_at,
                include_tool_limit=True,
                strict_current=False,
            ),
        }

    def _record_task_usage(
        self,
        task: RuntimeTaskRow,
        usage: dict[str, Any],
        *,
        now: float,
    ) -> RuntimeBudgetLedgerRow:
        row = self.session.scalar(
            select(RuntimeBudgetTaskUsageRow)
            .where(RuntimeBudgetTaskUsageRow.task_id == task.id)
            .with_for_update()
        )
        if row is None:
            try:
                with self.session.begin_nested():
                    self.session.execute(
                        insert(RuntimeBudgetTaskUsageRow).values(
                            task_id=task.id,
                            plan_id=task.plan_id,
                            prompt_tokens=0,
                            completion_tokens=0,
                            cost_microunits=0,
                            updated_at=now,
                        )
                    )
            except IntegrityError:
                self.session.expire_all()
            row = self.session.scalar(
                select(RuntimeBudgetTaskUsageRow)
                .where(RuntimeBudgetTaskUsageRow.task_id == task.id)
                .with_for_update()
            )
        if row is None:
            raise ConflictError("runtime task usage row could not be created")

        prompt = _nonnegative_int(usage.get("prompt_tokens"))
        completion = _nonnegative_int(usage.get("completion_tokens"))
        cost = _nonnegative_int(usage.get("cost_microunits"))
        prompt_delta = max(0, prompt - int(row.prompt_tokens))
        completion_delta = max(0, completion - int(row.completion_tokens))
        cost_delta = max(0, cost - int(row.cost_microunits))
        row.prompt_tokens = max(int(row.prompt_tokens), prompt)
        row.completion_tokens = max(int(row.completion_tokens), completion)
        row.cost_microunits = max(int(row.cost_microunits), cost)
        row.updated_at = now

        ledger = self._ensure_ledger(task.plan_id)
        if prompt_delta or completion_delta or cost_delta:
            self.session.execute(
                update(RuntimeBudgetLedgerRow)
                .where(RuntimeBudgetLedgerRow.plan_id == task.plan_id)
                .values(
                    prompt_tokens=(
                        RuntimeBudgetLedgerRow.prompt_tokens + prompt_delta
                    ),
                    completion_tokens=(
                        RuntimeBudgetLedgerRow.completion_tokens
                        + completion_delta
                    ),
                    cost_microunits=(
                        RuntimeBudgetLedgerRow.cost_microunits + cost_delta
                    ),
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            self.session.expire_all()
            ledger = self._ensure_ledger(task.plan_id)
        self._sync_plan_usage(self._plan_row(task.plan_id), ledger)
        return ledger

    def heartbeat(
        self,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        *,
        lease_seconds: float,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        heartbeat_at = time.time() if now is None else float(now)
        result = super().heartbeat(
            task_id,
            attempt_id,
            claim_token,
            lease_seconds=lease_seconds,
            checkpoint=checkpoint,
            usage=usage,
            now=heartbeat_at,
        )
        task = self._task_row(task_id)
        ledger = (
            self._record_task_usage(task, usage, now=heartbeat_at)
            if usage is not None
            else self._ensure_ledger(task.plan_id)
        )
        plan = self._plan_row(task.plan_id)
        violation = self._budget_violation(
            plan,
            ledger,
            now=heartbeat_at,
            include_tool_limit=False,
            strict_current=False,
        )
        result["budget_state"] = self.budget_state(
            task.plan_id,
            now=heartbeat_at,
        )
        result["budget_violation"] = violation
        if violation is not None:
            self._append_governance_event_once(
                task.plan_id,
                "agent.budget.exceeded",
                (
                    "agent.budget.exceeded:dimension:"
                    + str(violation["dimension"])
                ),
                task_id=task_id,
                attempt_id=attempt_id,
                payload={
                    "turn_id": plan.subject_id,
                    "type": "budget.exceeded",
                    **violation,
                },
                created_at=heartbeat_at,
            )
        return result

    def _consume_tool_budget(
        self,
        plan: RuntimePlanRow,
        task: RuntimeTaskRow,
        consumption_key: str,
        *,
        now: float,
    ) -> dict[str, Any]:
        normalized_key = str(consumption_key or "")[:240]
        existing = self.session.scalar(
            select(RuntimeBudgetConsumptionRow).where(
                RuntimeBudgetConsumptionRow.plan_id == plan.id,
                RuntimeBudgetConsumptionRow.consumption_key
                == normalized_key,
            )
        )
        if existing is not None:
            state = self.budget_state(plan.id, now=now)
            state["deduplicated"] = True
            return state

        ledger = self._ensure_ledger(plan.id)
        violation = self._budget_violation(
            plan,
            ledger,
            now=now,
            include_tool_limit=False,
            strict_current=True,
        )
        if violation is None:
            limit = _positive_limit(
                loads(plan.budget_json, {}).get("max_tool_calls")
            )
            next_count = int(ledger.tool_calls) + 1
            if limit is not None and next_count > limit:
                violation = {
                    "dimension": "max_tool_calls",
                    "limit": limit,
                    "actual": next_count,
                    "message": (
                        "runtime budget exceeded: max_tool_calls "
                        f"{next_count}/{limit:g}"
                    ),
                }
        if violation is not None:
            event = self._append_governance_event_once(
                plan.id,
                "agent.budget.exceeded",
                f"agent.budget.exceeded:action:{normalized_key}",
                task_id=task.id,
                payload={
                    "turn_id": plan.subject_id,
                    "type": "budget.exceeded",
                    "action_key": normalized_key,
                    **violation,
                },
                created_at=now,
            )
            state = self.budget_state(plan.id, now=now)
            state["violation"] = deepcopy(violation)
            state["event"] = event
            state["deduplicated"] = bool(
                event.get("deduplicated", False)
            )
            return state

        consumption_id = new_id()
        try:
            with self.session.begin_nested():
                self.session.execute(
                    insert(RuntimeBudgetConsumptionRow).values(
                        id=consumption_id,
                        plan_id=plan.id,
                        task_id=task.id,
                        consumption_key=normalized_key,
                        tool_calls=1,
                        cost_microunits=0,
                        created_at=now,
                    )
                )
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimeBudgetConsumptionRow).where(
                    RuntimeBudgetConsumptionRow.plan_id == plan.id,
                    RuntimeBudgetConsumptionRow.consumption_key
                    == normalized_key,
                )
            )
            if existing is None:
                raise
            state = self.budget_state(plan.id, now=now)
            state["deduplicated"] = True
            return state

        self.session.execute(
            update(RuntimeBudgetLedgerRow)
            .where(RuntimeBudgetLedgerRow.plan_id == plan.id)
            .values(
                tool_calls=RuntimeBudgetLedgerRow.tool_calls + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        ledger = self._ensure_ledger(plan.id)
        self._sync_plan_usage(plan, ledger)
        self.append_event(
            plan.id,
            "plan.budget.consumed",
            task_id=task.id,
            payload={
                "consumption_key": normalized_key,
                "tool_calls": 1,
                "usage": loads(plan.usage_json, {}),
            },
            created_at=now,
        )
        state = self.budget_state(plan.id, now=now)
        state["deduplicated"] = False
        return state

    def _fail_queued_for_budget(
        self,
        task: RuntimeTaskRow,
        violation: dict[str, Any],
        *,
        now: float,
    ) -> None:
        changed = self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task.id,
                RuntimeTaskRow.status == "queued",
            )
            .values(
                status="failed",
                error=str(violation["message"]),
                claim_token="",
                claim_owner="",
                claim_until=None,
                completed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return
        plan = self._plan_row(task.plan_id)
        self.append_event(
            task.plan_id,
            "agent.budget.exceeded",
            task_id=task.id,
            payload={
                "turn_id": plan.subject_id,
                "type": "budget.exceeded",
                **violation,
            },
            created_at=now,
        )
        self.reconcile_plan(task.plan_id, now=now)

    def claim_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        checked_at = time.time() if now is None else float(now)
        task = self._task_row(task_id)
        plan = self._plan_row(task.plan_id)
        # Agent domain state must be finalized by its handler so the Turn,
        # assistant message, and durable done event remain consistent. The
        # executor performs a governed heartbeat immediately after claim.
        if plan.kind == AGENT_PLAN_KIND:
            return super().claim_task(
                task_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=checked_at,
            )
        ledger = self._ensure_ledger(plan.id)
        violation = self._budget_violation(
            plan,
            ledger,
            now=checked_at,
            include_tool_limit=False,
            strict_current=True,
        )
        if violation is not None:
            self._fail_queued_for_budget(task, violation, now=checked_at)
            return None
        return super().claim_task(
            task_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=checked_at,
        )


__all__ = ["RuntimeBudgetRepositoryMixin"]
