"""Composed durable runtime governance repository."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .repositories import ConflictError
from .runtime_budget_repository import (
    RuntimeBudgetRepositoryMixin,
    _nonnegative_int,
)
from .runtime_governance_events import RuntimeGovernanceEventMixin
from .runtime_governance_models import (
    RuntimeBudgetLedgerRow,
    RuntimeBudgetTaskUsageRow,
)
from .runtime_policy_queries import RuntimePolicyQueryMixin
from .runtime_policy_repository import RuntimePolicyRepositoryMixin
from .task_runtime_extensions import (
    AGENT_PLAN_KIND,
    ControlledTaskRuntimeRepository,
)
from .task_runtime_models import RuntimeTaskRow

DEFAULT_AGENT_POLICY: dict[str, Any] = {
    "version": "agent-runtime-policy@1",
    "confirmation_risk_levels": ["high"],
    "denied_actions": [],
    "allowed_actions": [],
}
DEFAULT_AGENT_BUDGET: dict[str, Any] = {
    "max_prompt_tokens": 120_000,
    "max_completion_tokens": 60_000,
    "max_total_tokens": 160_000,
    "max_tool_calls": 12,
    "max_wall_seconds": 900,
}


class GovernedTaskRuntimeRepository(
    RuntimePolicyQueryMixin,
    RuntimePolicyRepositoryMixin,
    RuntimeBudgetRepositoryMixin,
    RuntimeGovernanceEventMixin,
    ControlledTaskRuntimeRepository,
):
    """Database-backed policy, budget, admission, and execution state."""

    @staticmethod
    def _decision(row):
        """Bind the mixin serializer without turning it into an instance call."""

        return RuntimePolicyRepositoryMixin._decision(row)

    def _record_task_usage(
        self,
        task: RuntimeTaskRow,
        usage: dict[str, Any],
        *,
        now: float,
    ) -> RuntimeBudgetLedgerRow:
        """Persist the task watermark before expiring the identity map.

        The base implementation introduced the durable ledger, but it expired
        ORM state before flushing the per-Task absolute watermark. Repeated
        heartbeats could therefore recount the same tokens. Keeping the fix in
        the composed repository preserves the original runtime layer while the
        governance extension owns its aggregate accounting semantics.
        """

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
        self.session.flush()

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

    def create_plan(
        self,
        *,
        project_id: str,
        kind: str,
        subject_type: str = "",
        subject_id: str = "",
        idempotency_key: str | None = None,
        priority: int = 0,
        input: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if str(kind) == AGENT_PLAN_KIND:
            policy = {**DEFAULT_AGENT_POLICY, **deepcopy(policy or {})}
            budget = {**DEFAULT_AGENT_BUDGET, **deepcopy(budget or {})}
        plan = super().create_plan(
            project_id=project_id,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            priority=priority,
            input=input,
            policy=policy,
            budget=budget,
        )
        # Plan intent and its zero-value ledger commit together, so read-only
        # budget observability never has to create execution state.
        self._ensure_ledger(plan["id"])
        return plan


__all__ = [
    "DEFAULT_AGENT_BUDGET",
    "DEFAULT_AGENT_POLICY",
    "GovernedTaskRuntimeRepository",
]
