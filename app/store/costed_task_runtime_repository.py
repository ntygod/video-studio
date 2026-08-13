"""Final Runtime repository composition with immutable Provider costs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain.provider_pricing import (
    normalize_microunits,
    usd_to_microunits,
)

from .runtime_cost_repository import RuntimeCostRepositoryMixin
from .task_runtime_extensions import AGENT_PLAN_KIND
from .task_runtime_governance import GovernedTaskRuntimeRepository

DEFAULT_AGENT_MAX_COST_MICROUNITS = 10_000_000


class CostedTaskRuntimeRepository(
    RuntimeCostRepositoryMixin,
    GovernedTaskRuntimeRepository,
):
    """Governed runtime plus Provider pricing and cost-ledger semantics."""

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
        normalized_budget = deepcopy(budget or {})
        if normalized_budget.get("max_cost_microunits") is not None:
            normalized_budget["max_cost_microunits"] = (
                normalize_microunits(
                    normalized_budget["max_cost_microunits"],
                    field="max_cost_microunits",
                )
            )
        if (
            normalized_budget.get("max_cost_microunits") is None
            and normalized_budget.get("max_cost_usd") is not None
        ):
            normalized_budget["max_cost_microunits"] = usd_to_microunits(
                normalized_budget.pop("max_cost_usd"),
                field="max_cost_usd",
            )
        if (
            str(kind) == AGENT_PLAN_KIND
            and normalized_budget.get("max_cost_microunits") is None
        ):
            normalized_budget["max_cost_microunits"] = (
                DEFAULT_AGENT_MAX_COST_MICROUNITS
            )
        return super().create_plan(
            project_id=project_id,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            priority=priority,
            input=input,
            policy=policy,
            budget=normalized_budget,
        )


__all__ = [
    "CostedTaskRuntimeRepository",
    "DEFAULT_AGENT_MAX_COST_MICROUNITS",
]
