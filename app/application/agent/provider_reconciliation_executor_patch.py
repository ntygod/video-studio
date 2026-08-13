"""Install Provider reconciliation on the durable Agent executor."""

from app.application.reconciled_task_runtime import ReconciledTaskRuntime

from .durable_executor import DurableAgentTurnExecutor

_INSTALLED = False


def install_provider_reconciliation_executor() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_init = DurableAgentTurnExecutor.__init__

    def reconciled_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._engine.runtime = ReconciledTaskRuntime(self.database)

    DurableAgentTurnExecutor.__init__ = reconciled_init


__all__ = ["install_provider_reconciliation_executor"]
