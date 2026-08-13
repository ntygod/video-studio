"""Immutable Provider usage costs and hard RuntimePlan cost budgets."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.provider_pricing import (
    microunits_to_usd,
    price_llm_usage,
    usd_to_microunits,
)

from .json_codec import dumps, loads
from .repositories import ConflictError, NotFoundError, new_id
from .runtime_cost_models import RuntimeCostEntryRow
from .runtime_governance_models import (
    RuntimeBudgetLedgerRow,
    RuntimeBudgetTaskUsageRow,
)
from .task_runtime_models import RuntimeTaskAttemptRow, RuntimeTaskRow


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class RuntimeCostRepositoryMixin:
    @staticmethod
    def _cost_entry(row: RuntimeCostEntryRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "task_id": row.task_id,
            "attempt_id": row.attempt_id,
            "usage_key": row.usage_key,
            "source_type": row.source_type,
            "provider_profile_id": row.provider_profile_id,
            "provider_name": row.provider_name,
            "adapter": row.adapter,
            "model_profile_id": row.model_profile_id,
            "model_id": row.model_id,
            "capability_type": row.capability_type,
            "provider_request_id": row.provider_request_id,
            "currency": row.currency,
            "pricing_sha256": row.pricing_sha256,
            "pricing_snapshot": loads(row.pricing_snapshot_json, {}),
            "usage": loads(row.usage_json, {}),
            "breakdown": loads(row.breakdown_json, {}),
            "amount_microunits": int(row.amount_microunits),
            "amount_usd": microunits_to_usd(row.amount_microunits),
            "priced": bool(row.priced),
            "created_at": row.created_at,
        }

    def get_cost_entry(self, entry_id: str) -> dict[str, Any]:
        row = self.session.get(RuntimeCostEntryRow, entry_id)
        if row is None:
            raise NotFoundError(entry_id)
        return self._cost_entry(row)

    def list_cost_entries(
        self,
        plan_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._plan_row(plan_id)
        safe_limit = max(1, min(int(limit), 500))
        rows = self.session.scalars(
            select(RuntimeCostEntryRow)
            .where(RuntimeCostEntryRow.plan_id == plan_id)
            .order_by(
                RuntimeCostEntryRow.created_at.desc(),
                RuntimeCostEntryRow.id.desc(),
            )
            .limit(safe_limit)
        ).all()
        return [self._cost_entry(row) for row in rows]

    def _cost_counts(self, plan_id: str) -> dict[str, int]:
        row = self.session.execute(
            select(
                func.count(RuntimeCostEntryRow.id),
                func.coalesce(
                    func.sum(
                        case(
                            (RuntimeCostEntryRow.priced.is_(True), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(RuntimeCostEntryRow.plan_id == plan_id)
        ).one()
        total = int(row[0] or 0)
        priced = int(row[1] or 0)
        return {
            "provider_calls": total,
            "priced_calls": priced,
            "unpriced_calls": max(0, total - priced),
        }

    @staticmethod
    def _cost_limit_microunits(budget: dict[str, Any]) -> int | None:
        if budget.get("max_cost_microunits") is not None:
            return _nonnegative_int(budget.get("max_cost_microunits"))
        if budget.get("max_cost_usd") is not None:
            try:
                return usd_to_microunits(
                    budget.get("max_cost_usd"),
                    field="max_cost_usd",
                )
            except ValueError:
                return None
        return None

    def _budget_violation(
        self,
        plan,
        ledger,
        *,
        now: float,
        include_tool_limit: bool,
        strict_current: bool,
    ) -> dict[str, Any] | None:
        violation = super()._budget_violation(
            plan,
            ledger,
            now=now,
            include_tool_limit=include_tool_limit,
            strict_current=strict_current,
        )
        if violation is not None:
            return violation
        budget = loads(plan.budget_json, {})
        limit = self._cost_limit_microunits(budget)
        if limit is None:
            return None
        actual = int(ledger.cost_microunits)
        exceeded = actual >= limit if strict_current else actual > limit
        if not exceeded:
            return None
        return {
            "dimension": "max_cost_microunits",
            "limit": limit,
            "actual": actual,
            "limit_usd": microunits_to_usd(limit),
            "actual_usd": microunits_to_usd(actual),
            "message": (
                "runtime budget exceeded: max_cost_microunits "
                f"{actual}/{limit}"
            ),
        }

    def budget_state(
        self,
        plan_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        state = super().budget_state(plan_id, now=now)
        state["plan_status"] = self._plan_row(plan_id).status
        cost = int(state["usage"].get("cost_microunits") or 0)
        state["usage"]["cost_usd"] = microunits_to_usd(cost)
        state["usage"].update(self._cost_counts(plan_id))
        limit = self._cost_limit_microunits(state.get("budget") or {})
        if limit is not None:
            state["budget"]["max_cost_microunits"] = limit
            state["budget"]["max_cost_usd"] = microunits_to_usd(limit)
        return state

    def _ensure_cost_task_usage(
        self,
        task: RuntimeTaskRow,
        *,
        now: float,
    ) -> RuntimeBudgetTaskUsageRow:
        row = self.session.scalar(
            select(RuntimeBudgetTaskUsageRow)
            .where(RuntimeBudgetTaskUsageRow.task_id == task.id)
            .with_for_update()
        )
        if row is not None:
            return row
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
        return row

    def _append_budget_event(
        self,
        plan,
        task: RuntimeTaskRow,
        violation: dict[str, Any],
        *,
        attempt_id: str | None,
        suffix: str,
        now: float,
    ) -> dict[str, Any]:
        return self._append_governance_event_once(
            plan.id,
            "agent.budget.exceeded",
            (
                "agent.budget.exceeded:dimension:"
                + str(violation["dimension"])
                + ":"
                + suffix[:120]
            ),
            task_id=task.id,
            attempt_id=attempt_id,
            payload={
                "turn_id": plan.subject_id,
                "type": "budget.exceeded",
                **deepcopy(violation),
            },
            created_at=now,
        )

    def check_provider_budget(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        checked_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        task = self._task_row(task_id)
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if (
            task.plan_id != plan_id
            or task.status != "running"
            or task.claim_token != claim_token
            or attempt is None
            or attempt.task_id != task.id
            or attempt.status != "running"
            or attempt.claim_token != claim_token
        ):
            raise ConflictError(
                "runtime Provider budget check lost its Task lease"
            )
        ledger = self._ensure_ledger(plan_id)
        violation = self._budget_violation(
            plan,
            ledger,
            now=checked_at,
            include_tool_limit=False,
            strict_current=True,
        )
        event = None
        if violation is not None:
            event = self._append_budget_event(
                plan,
                task,
                violation,
                attempt_id=attempt_id,
                suffix="provider-precheck",
                now=checked_at,
            )
        state = self.budget_state(plan_id, now=checked_at)
        if violation is not None:
            state["violation"] = deepcopy(violation)
            state["event"] = event
        return state

    def record_provider_usage(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        usage_key: str,
        source_type: str,
        provider_snapshot: dict[str, Any],
        pricing_snapshot: dict[str, Any],
        usage: dict[str, Any],
        now: float | None = None,
    ) -> dict[str, Any]:
        recorded_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        task = self._task_row(task_id)
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if (
            task.plan_id != plan_id
            or attempt is None
            or attempt.task_id != task.id
            or attempt.plan_id != plan_id
            or attempt.claim_token != claim_token
        ):
            raise ConflictError(
                "runtime Provider usage does not belong to this Attempt"
            )
        normalized_key = str(usage_key or "").strip()[:240]
        if not normalized_key:
            raise ValueError("runtime Provider usage key is required")

        existing = self.session.scalar(
            select(RuntimeCostEntryRow).where(
                RuntimeCostEntryRow.plan_id == plan_id,
                RuntimeCostEntryRow.usage_key == normalized_key,
            )
        )
        if existing is not None:
            task_usage = self._ensure_cost_task_usage(
                task,
                now=recorded_at,
            )
            return {
                "entry": self._cost_entry(existing),
                "task_usage": {
                    "prompt_tokens": int(task_usage.prompt_tokens),
                    "completion_tokens": int(task_usage.completion_tokens),
                    "cost_microunits": int(task_usage.cost_microunits),
                },
                "budget_state": self.budget_state(
                    plan_id,
                    now=recorded_at,
                ),
                "deduplicated": True,
            }

        pricing_value = pricing_snapshot.get(
            "pricing",
            pricing_snapshot,
        )
        priced_usage = price_llm_usage(pricing_value, usage)
        normalized_usage = dict(priced_usage["usage"])
        provider_request_id = str(
            normalized_usage.get("provider_request_id") or ""
        )
        entry_id = new_id()
        try:
            with self.session.begin_nested():
                self.session.execute(
                    insert(RuntimeCostEntryRow).values(
                        id=entry_id,
                        plan_id=plan_id,
                        task_id=task_id,
                        attempt_id=attempt_id,
                        usage_key=normalized_key,
                        source_type=str(source_type or "provider")[:80],
                        provider_profile_id=str(
                            provider_snapshot.get("provider_profile_id")
                            or ""
                        )[:64],
                        provider_name=str(
                            provider_snapshot.get("provider_name") or ""
                        )[:200],
                        adapter=str(
                            provider_snapshot.get("adapter") or ""
                        )[:100],
                        model_profile_id=str(
                            provider_snapshot.get("model_profile_id") or ""
                        )[:64],
                        model_id=str(
                            provider_snapshot.get("model_id") or ""
                        )[:300],
                        capability_type=str(
                            provider_snapshot.get("capability_type") or ""
                        )[:50],
                        provider_request_id=provider_request_id[:300],
                        currency=str(priced_usage["currency"])[:12],
                        pricing_sha256=str(
                            priced_usage["pricing_sha256"]
                        )[:64],
                        pricing_snapshot_json=dumps(
                            deepcopy(pricing_snapshot)
                        ),
                        usage_json=dumps(normalized_usage),
                        breakdown_json=dumps(priced_usage["breakdown"]),
                        amount_microunits=int(
                            priced_usage["amount_microunits"]
                        ),
                        priced=bool(priced_usage["priced"]),
                        created_at=recorded_at,
                    )
                )
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimeCostEntryRow).where(
                    RuntimeCostEntryRow.plan_id == plan_id,
                    RuntimeCostEntryRow.usage_key == normalized_key,
                )
            )
            if existing is None:
                raise
            task = self._task_row(task_id)
            task_usage = self._ensure_cost_task_usage(
                task,
                now=recorded_at,
            )
            return {
                "entry": self._cost_entry(existing),
                "task_usage": {
                    "prompt_tokens": int(task_usage.prompt_tokens),
                    "completion_tokens": int(task_usage.completion_tokens),
                    "cost_microunits": int(task_usage.cost_microunits),
                },
                "budget_state": self.budget_state(
                    plan_id,
                    now=recorded_at,
                ),
                "deduplicated": True,
            }

        prompt_delta = int(normalized_usage["prompt_tokens"])
        completion_delta = int(normalized_usage["completion_tokens"])
        cost_delta = int(priced_usage["amount_microunits"])
        self._ensure_cost_task_usage(task, now=recorded_at)
        self._ensure_ledger(plan_id)
        self.session.execute(
            update(RuntimeBudgetTaskUsageRow)
            .where(RuntimeBudgetTaskUsageRow.task_id == task_id)
            .values(
                prompt_tokens=(
                    RuntimeBudgetTaskUsageRow.prompt_tokens + prompt_delta
                ),
                completion_tokens=(
                    RuntimeBudgetTaskUsageRow.completion_tokens
                    + completion_delta
                ),
                cost_microunits=(
                    RuntimeBudgetTaskUsageRow.cost_microunits + cost_delta
                ),
                updated_at=recorded_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.execute(
            update(RuntimeBudgetLedgerRow)
            .where(RuntimeBudgetLedgerRow.plan_id == plan_id)
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
                updated_at=recorded_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        task = self._task_row(task_id)
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        task_usage_row = self._ensure_cost_task_usage(
            task,
            now=recorded_at,
        )
        task_usage = loads(task.usage_json, {})
        task_usage.update(
            {
                "prompt_tokens": int(task_usage_row.prompt_tokens),
                "completion_tokens": int(task_usage_row.completion_tokens),
                "cost_microunits": int(task_usage_row.cost_microunits),
            }
        )
        task.usage_json = dumps(task_usage)
        if attempt is not None:
            attempt_usage = loads(attempt.usage_json, {})
            attempt_usage.update(task_usage)
            attempt.usage_json = dumps(attempt_usage)
        ledger = self._ensure_ledger(plan_id)
        plan = self._plan_row(plan_id)
        self._sync_plan_usage(plan, ledger)
        self.session.flush()
        row = self.session.get(RuntimeCostEntryRow, entry_id)
        if row is None:
            raise ConflictError("runtime cost entry was not persisted")
        entry = self._cost_entry(row)
        self.append_event(
            plan_id,
            "plan.cost.recorded",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "cost_entry_id": entry_id,
                "usage_key": normalized_key,
                "source_type": entry["source_type"],
                "provider_profile_id": entry["provider_profile_id"],
                "model_id": entry["model_id"],
                "amount_microunits": entry["amount_microunits"],
                "amount_usd": entry["amount_usd"],
                "priced": entry["priced"],
            },
            created_at=recorded_at,
        )
        violation = self._budget_violation(
            plan,
            ledger,
            now=recorded_at,
            include_tool_limit=True,
            strict_current=False,
        )
        budget_event = None
        if violation is not None:
            budget_event = self._append_budget_event(
                plan,
                task,
                violation,
                attempt_id=attempt_id,
                suffix="provider:" + entry_id,
                now=recorded_at,
            )
        state = self.budget_state(plan_id, now=recorded_at)
        if violation is not None:
            state["violation"] = deepcopy(violation)
            state["event"] = budget_event
        return {
            "entry": entry,
            "task_usage": task_usage,
            "budget_state": state,
            "deduplicated": False,
        }


__all__ = ["RuntimeCostRepositoryMixin"]
