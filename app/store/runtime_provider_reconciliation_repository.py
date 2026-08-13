"""Provider reconciliation candidate query."""

from __future__ import annotations

from sqlalchemy import select

from .runtime_provider_request_models import RuntimeProviderRequestRow
from .task_runtime_models import RuntimePlanRow


class RuntimeProviderReconciliationQueryMixin:
    def list_reconcilable_provider_request_ids(
        self,
        *,
        kinds=None,
        limit=50,
    ):
        statement = select(RuntimeProviderRequestRow.id).join(
            RuntimePlanRow,
            RuntimePlanRow.id == RuntimeProviderRequestRow.plan_id,
        ).where(
            RuntimeProviderRequestRow.status == "outcome_unknown",
            RuntimeProviderRequestRow.provider_request_id != "",
        )
        if kinds is not None:
            normalized = tuple(str(item) for item in kinds if str(item))
            if not normalized:
                return []
            statement = statement.where(RuntimePlanRow.kind.in_(normalized))
        return list(
            self.session.scalars(
                statement.order_by(
                    RuntimeProviderRequestRow.updated_at,
                    RuntimeProviderRequestRow.id,
                ).limit(max(1, min(int(limit), 500)))
            ).all()
        )


__all__ = ["RuntimeProviderReconciliationQueryMixin"]
