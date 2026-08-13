"""Application-side helpers for durable runtime policy and budget enforcement."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Callable

from app.application.task_runtime import TaskRuntime
from app.application.task_runtime_engine import TaskExecutionContext
from app.store import UnitOfWork

LiveEmitter = Callable[[dict[str, Any]], None]


class PolicyApprovalRequired(BaseException):
    """Control-flow signal that pauses a durable Task for user approval."""

    def __init__(self, decision: dict[str, Any]):
        self.decision = decision
        super().__init__(
            str(decision.get("reason") or "runtime action requires approval")
        )


class RuntimeBudgetExceeded(BaseException):
    """Control-flow signal raised only after governance state is durable."""

    def __init__(self, violation: dict[str, Any]):
        self.violation = dict(violation)
        super().__init__(
            str(violation.get("message") or "runtime budget exceeded")
        )


@dataclass(frozen=True, slots=True)
class RuntimeExecutionBinding:
    context: TaskExecutionContext
    turn_id: str
    live_emit: LiveEmitter | None = None


_current_binding: ContextVar[RuntimeExecutionBinding | None] = ContextVar(
    "video_studio_runtime_execution_binding",
    default=None,
)


def bind_runtime_execution(
    context: TaskExecutionContext,
    *,
    turn_id: str,
    live_emit: LiveEmitter | None = None,
) -> Token:
    return _current_binding.set(
        RuntimeExecutionBinding(
            context=context,
            turn_id=turn_id,
            live_emit=live_emit,
        )
    )


def reset_runtime_execution(token: Token) -> None:
    _current_binding.reset(token)


def current_runtime_execution() -> RuntimeExecutionBinding | None:
    return _current_binding.get()


class GovernedTaskRuntime(TaskRuntime):
    """TaskRuntime facade that enforces committed governance state."""

    def heartbeat(self, *args, **kwargs):
        result = super().heartbeat(*args, **kwargs)
        violation = result.get("budget_violation")
        if violation and current_runtime_execution() is not None:
            raise RuntimeBudgetExceeded(violation)
        return result

    def recover(self, *, kinds=None, now=None) -> int:
        normalized_kinds = tuple(kinds) if kinds is not None else None
        recovered = super().recover(kinds=normalized_kinds, now=now)
        with UnitOfWork(self.database) as uow:
            unknown_requests = (
                uow.task_runtime.recover_stale_provider_requests(
                    kinds=normalized_kinds,
                    now=now,
                )
            )
            expired = uow.task_runtime.expire_pending_policy_decisions(
                kinds=normalized_kinds,
                now=now,
            )
        return recovered + unknown_requests + expired


__all__ = [
    "GovernedTaskRuntime",
    "PolicyApprovalRequired",
    "RuntimeBudgetExceeded",
    "RuntimeExecutionBinding",
    "bind_runtime_execution",
    "current_runtime_execution",
    "reset_runtime_execution",
]
