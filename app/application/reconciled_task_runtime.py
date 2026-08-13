"""Runtime facade that includes Provider status reconciliation."""

from app.application.provider_request_recovery import (
    reconcile_provider_requests,
)
from app.application.runtime_governance import GovernedTaskRuntime
from app.store import UnitOfWork


class ReconciledTaskRuntime(GovernedTaskRuntime):
    def recover(self, *, kinds=None, now=None) -> int:
        recovered = super().recover(kinds=kinds, now=now)
        with UnitOfWork(self.database) as uow:
            request_ids = (
                uow.task_runtime.list_reconcilable_provider_request_ids(
                    kinds=kinds,
                    limit=50,
                )
            )
        return recovered + reconcile_provider_requests(
            self.database,
            request_ids,
        )


__all__ = ["ReconciledTaskRuntime"]
