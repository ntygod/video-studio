"""Final Runtime repository composition with immutable Provider costs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.jobs.runtime_contract import MEDIA_JOB_PLAN_KIND
from app.domain.project import ProjectSettings, RuntimeCostPolicy
from app.domain.provider_pricing import (
    normalize_microunits,
    usd_to_microunits,
)

from .json_codec import loads
from .models import ProjectRow
from .repositories import NotFoundError
from .runtime_cost_policy_repository import (
    RuntimeCostPolicyRepositoryMixin,
)
from .runtime_cost_repository import RuntimeCostRepositoryMixin
from .runtime_provider_reconciliation_repository import (
    RuntimeProviderReconciliationQueryMixin,
)
from .runtime_provider_request_repository import (
    RuntimeProviderRequestRepositoryMixin,
)
from .task_runtime_extensions import AGENT_PLAN_KIND
from .task_runtime_governance import GovernedTaskRuntimeRepository

DEFAULT_AGENT_MAX_COST_MICROUNITS = 10_000_000
COST_GOVERNED_PLAN_KINDS = frozenset(
    {AGENT_PLAN_KIND, MEDIA_JOB_PLAN_KIND}
)


class CostedTaskRuntimeRepository(
    RuntimeProviderReconciliationQueryMixin,
    RuntimeProviderRequestRepositoryMixin,
    RuntimeCostPolicyRepositoryMixin,
    RuntimeCostRepositoryMixin,
    GovernedTaskRuntimeRepository,
):
    """Governed runtime plus Provider request and cost-ledger semantics."""

    def _project_provider_cost_policy(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        row = self.session.get(ProjectRow, project_id)
        if row is None:
            raise NotFoundError(project_id)
        settings = ProjectSettings.model_validate(
            loads(row.settings_json, {})
        )
        return settings.runtime_cost_policy.model_dump(mode="json")

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

        normalized_policy = deepcopy(policy or {})
        if str(kind) in COST_GOVERNED_PLAN_KINDS:
            configured = normalized_policy.get("provider_cost_policy")
            if configured is None:
                configured = self._project_provider_cost_policy(project_id)
            normalized_policy["provider_cost_policy"] = (
                RuntimeCostPolicy.model_validate(configured).model_dump(
                    mode="json"
                )
            )

        return super().create_plan(
            project_id=project_id,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            priority=priority,
            input=input,
            policy=normalized_policy,
            budget=normalized_budget,
        )


__all__ = [
    "COST_GOVERNED_PLAN_KINDS",
    "CostedTaskRuntimeRepository",
    "DEFAULT_AGENT_MAX_COST_MICROUNITS",
]
