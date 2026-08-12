"""Read models for project-wide runtime policy decision discovery."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .json_codec import loads
from .runtime_governance_models import RuntimePolicyDecisionRow
from .task_runtime_models import RuntimePlanRow


class RuntimePolicyQueryMixin:
    """Project-scoped policy queries without an N+1 Plan lookup."""

    def list_project_policy_decisions(
        self,
        project_id: str,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        statement = (
            select(RuntimePolicyDecisionRow, RuntimePlanRow)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimePolicyDecisionRow.plan_id,
            )
            .where(RuntimePlanRow.project_id == project_id)
        )
        if status:
            statement = statement.where(
                RuntimePolicyDecisionRow.status == status
            )
        if kind:
            statement = statement.where(RuntimePlanRow.kind == kind)
        rows = self.session.execute(
            statement.order_by(
                RuntimePolicyDecisionRow.created_at.desc(),
                RuntimePolicyDecisionRow.id.desc(),
            ).limit(limit)
        ).all()
        result: list[dict[str, Any]] = []
        for decision, plan in rows:
            item = self._decision(decision)
            item["plan"] = {
                "id": plan.id,
                "project_id": plan.project_id,
                "kind": plan.kind,
                "subject_type": plan.subject_type,
                "subject_id": plan.subject_id,
                "status": plan.status,
                "input": loads(plan.input_json, {}),
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
            }
            result.append(item)
        return result


__all__ = ["RuntimePolicyQueryMixin"]
