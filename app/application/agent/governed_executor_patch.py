"""Install runtime governance around the durable Agent executor.

Kept as a focused patch module so the durable executor remains readable and
can continue serving legacy/non-governed tests. Importing ``app.application.agent``
installs these method wrappers exactly once.
"""

from __future__ import annotations

from typing import Any

from app.api.logging import request_id_var
from app.application.runtime_governance import (
    GovernedTaskRuntime,
    PolicyApprovalRequired,
    RuntimeBudgetExceeded,
    bind_runtime_execution,
    reset_runtime_execution,
)
from app.application.task_runtime_engine import (
    RetryableTaskError,
    TaskExecutionCanceled,
    TaskExecutionContext,
)
from app.store.repositories import ConflictError

from .durable_executor import DurableAgentTurnExecutor

_INSTALLED = False


def _emit_terminal_failure(
    executor: DurableAgentTurnExecutor,
    context: TaskExecutionContext,
    turn_id: str,
    request_id: str,
    error_text: str,
) -> None:
    message_id = executor._mark_turn_failed(
        context,
        turn_id,
        request_id,
        error_text,
    )
    context.emit(
        "agent.error",
        {
            "turn_id": turn_id,
            "type": "error",
            "message": error_text,
            "recoverable": False,
        },
    )
    context.emit(
        "agent.message",
        {
            "turn_id": turn_id,
            "type": "message",
            "message_id": message_id,
            "text": f"执行失败：{error_text}",
        },
    )
    context.emit(
        "agent.done",
        {
            "turn_id": turn_id,
            "type": "done",
            "message_id": message_id,
            "usage": {
                "prompt": int(context.usage.get("prompt_tokens") or 0),
                "completion": int(
                    context.usage.get("completion_tokens") or 0
                ),
            },
            "canceled": False,
            "failed": True,
        },
    )
    executor._finish_future(
        turn_id,
        error=RuntimeError(error_text),
    )


def install_governed_agent_executor() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_init = DurableAgentTurnExecutor.__init__

    def governed_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # A budget violation is raised only after its usage/checkpoint
        # transaction has committed.
        self._engine.runtime = GovernedTaskRuntime(self.database)

    def notify(self) -> None:
        """Wake durable workers after approval or another external transition."""
        self.start()
        self._engine.notify()

    def append_missing_event(
        self,
        context: TaskExecutionContext,
        turn_id: str,
        event_type: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        stored = context.emit(
            event_type,
            {"turn_id": turn_id, **event},
        )
        if not stored.get("deduplicated"):
            self._emit(
                turn_id,
                {
                    "id": f"{turn_id}:{stored['seq']}",
                    "seq": stored["seq"],
                    **event,
                },
            )
        return stored

    def handle_turn(
        self,
        context: TaskExecutionContext,
    ) -> dict[str, Any]:
        payload = dict(context.task.get("payload") or {})
        turn_id = str(
            payload.get("turn_id")
            or context.plan.get("subject_id")
            or ""
        )
        if not turn_id:
            raise RuntimeError("Agent RuntimeTask has no turn_id")
        request_id = str(payload.get("request_id") or "")
        request_token = request_id_var.set(request_id)
        binding_token = bind_runtime_execution(
            context,
            turn_id=turn_id,
            live_emit=lambda event: self._emit(turn_id, event),
        )
        try:
            # Enforce wall-clock and already-recorded usage before a resumed
            # Agent makes another provider or tool call.
            context.heartbeat()
            result = self._runner(
                self.database,
                self.settings,
                self.job_engine,
                context,
                live_emit=lambda event: self._emit(turn_id, event),
                request_id=request_id,
            )
            self._ensure_success_events(context, turn_id, result)
            self._finish_future(turn_id, result=result)
            return result
        except PolicyApprovalRequired as exc:
            # Decision, event, checkpoint, and suspended Attempt were committed
            # atomically by the governed tool wrapper.
            raise ConflictError(
                f"Agent turn is waiting for approval: {exc.decision['id']}"
            ) from None
        except RuntimeBudgetExceeded as exc:
            error_text = str(exc)
            _emit_terminal_failure(
                self,
                context,
                turn_id,
                request_id,
                error_text,
            )
            raise RuntimeError(error_text) from None
        except TaskExecutionCanceled:
            self._mark_turn_canceled(turn_id)
            self._finish_future(turn_id, canceled=True)
            raise
        except ConflictError:
            # A newer Attempt, timeout recovery, suspension, or cancellation
            # owns state.
            raise
        except Exception as exc:
            error_text = str(exc)
            attempt = int(context.task.get("attempt_count") or 0)
            max_attempts = int(context.task.get("max_attempts") or 1)
            if attempt < max_attempts:
                try:
                    context.emit(
                        "agent.error",
                        {
                            "turn_id": turn_id,
                            "type": "error",
                            "message": error_text,
                            "recoverable": True,
                            "attempt": attempt,
                        },
                    )
                except ConflictError:
                    raise
                raise RetryableTaskError(
                    error_text,
                    backoff_seconds=min(2 ** max(attempt - 1, 0), 30),
                    checkpoint=context.checkpoint,
                    usage=context.usage,
                ) from exc
            _emit_terminal_failure(
                self,
                context,
                turn_id,
                request_id,
                error_text,
            )
            raise RuntimeError(error_text) from exc
        finally:
            reset_runtime_execution(binding_token)
            request_id_var.reset(request_token)

    DurableAgentTurnExecutor.__init__ = governed_init
    DurableAgentTurnExecutor.notify = notify
    DurableAgentTurnExecutor._append_missing_event = append_missing_event
    DurableAgentTurnExecutor._handle_turn = handle_turn


__all__ = ["install_governed_agent_executor"]
