"""Provider reconciliation candidate query."""

from __future__ import annotations

import time

from sqlalchemy import select

from .runtime_provider_request_models import RuntimeProviderRequestRow
from .task_runtime_models import RuntimePlanRow

RECONCILIATION_POLL_SECONDS = 15.0


class RuntimeProviderReconciliationQueryMixin:
    def list_reconcilable_provider_request_ids(
        self,
        *,
        kinds=None,
        limit=50,
        now=None,
    ):
        checked_at = time.time() if now is None else float(now)
        statement = select(RuntimeProviderRequestRow.id).join(
            RuntimePlanRow,
            RuntimePlanRow.id == RuntimeProviderRequestRow.plan_id,
        ).where(
            RuntimeProviderRequestRow.status == "outcome_unknown",
            RuntimeProviderRequestRow.provider_request_id != "",
            RuntimeProviderRequestRow.updated_at
            <= checked_at - RECONCILIATION_POLL_SECONDS,
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


__all__ = [
    "RECONCILIATION_POLL_SECONDS",
    "RuntimeProviderReconciliationQueryMixin",
]
