"""Composed durable runtime governance repository."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .runtime_budget_repository import RuntimeBudgetRepositoryMixin
from .runtime_governance_events import RuntimeGovernanceEventMixin
from .runtime_policy_repository import RuntimePolicyRepositoryMixin
from .task_runtime_extensions import (
    AGENT_PLAN_KIND,
    ControlledTaskRuntimeRepository,
)

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
    RuntimePolicyRepositoryMixin,
    RuntimeBudgetRepositoryMixin,
    RuntimeGovernanceEventMixin,
    ControlledTaskRuntimeRepository,
):
    """Database-backed policy, budget, admission, and execution state."""

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
        return super().create_plan(
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


__all__ = [
    "DEFAULT_AGENT_BUDGET",
    "DEFAULT_AGENT_POLICY",
    "GovernedTaskRuntimeRepository",
]
