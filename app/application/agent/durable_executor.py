"""Production executor that runs Agent Turns on the durable task runtime."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Callable

from app.api.logging import request_id_var
from app.application.task_runtime_engine import (
    RetryableTaskError,
    TaskExecutionCanceled,
    TaskExecutionContext,
    TaskRuntimeEngine,
)
from app.store import UnitOfWork
from app.store.models import AgentStepRow
from app.store.repositories import ConflictError
from app.store.task_runtime_models import RuntimeTaskRow

from .durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
    run_durable_agent_turn,
)
from .executor import (
    DEFAULT_MAX_QUEUED,
    DEFAULT_WORKERS,
    _register_shutdown,
)

LiveEmitter = Callable[[dict[str, Any]], None]
DurableTurnRunner = Callable[..., dict[str, Any]]


class DurableAgentTurnExecutor:
    """Compatibility facade over ``TaskRuntimeEngine`` for HTTP routes.

    ``submit`` no longer owns queue durability. It only installs a live event
    emitter, ensures a safe legacy Turn has a RuntimePlan, and wakes workers.
    The database remains the source of truth across process restarts.
    """

    def __init__(
        self,
        database,
        settings,
        job_engine,
        *,
        workers: int = DEFAULT_WORKERS,
        max_queued: int = DEFAULT_MAX_QUEUED,
        runner: DurableTurnRunner = run_durable_agent_turn,
    ):
        self.database = database
        self.settings = settings
        self.job_engine = job_engine
        self.workers = max(1, int(workers))
        self.max_queued = max(0, int(max_queued))
        self._runner = runner
        self._lock = threading.Lock()
        self._emitters: dict[str, LiveEmitter] = {}
        self._futures: dict[str, Future] = {}
        self._started = False
        self._closed = False
        self._engine = TaskRuntimeEngine(
            database,
            kinds={AGENT_PLAN_KIND},
            workers=self.workers,
            lease_seconds=60,
            heartbeat_interval=10,
            recovery_interval=2,
            engine_id=f"agent-runtime-{uuid.uuid4().hex[:10]}",
        )
        self._engine.register(AGENT_TASK_TYPE, self._handle_turn)

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Agent executor is closed")
            if self._started:
                return
            self._started = True
        self._engine.start()

    def _ensure_plan(
        self,
        turn_id: str,
        request_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with UnitOfWork(self.database) as uow:
            turn = uow.agent_turns.get(turn_id)
            plan = uow.task_runtime.find_plan_by_subject(
                "agent_turn",
                turn_id,
                kind=AGENT_PLAN_KIND,
            )
            if plan is not None or turn["status"] != "running":
                return plan, turn

            # Upgrade recovery for a legacy Turn that never began executing.
            # Once any Step or entity exists, replaying the old in-memory loop
            # from the beginning is not proven safe, so fail closed instead.
            if turn.get("steps") or turn.get("created_entities"):
                raise RuntimeError(
                    "legacy Agent turn has side effects but no durable Plan"
                )
            plan = uow.task_runtime.create_plan(
                project_id=turn["project_id"],
                kind=AGENT_PLAN_KIND,
                subject_type="agent_turn",
                subject_id=turn_id,
                idempotency_key=f"agent-turn:{turn_id}",
                input={
                    "conversation_id": turn["conversation_id"],
                    "request_id": request_id,
                    "legacy_adopted": True,
                },
            )
            uow.task_runtime.add_task(
                plan["id"],
                task_key="execute",
                task_type=AGENT_TASK_TYPE,
                payload={
                    "turn_id": turn_id,
                    "request_id": request_id,
                },
                max_attempts=3,
                timeout_seconds=900,
            )
            plan = uow.task_runtime.queue_plan(plan["id"])
            return plan, turn

    def submit(
        self,
        turn_id: str,
        emit: LiveEmitter,
        *,
        request_id: str = "",
    ) -> Future:
        plan, turn = self._ensure_plan(turn_id, request_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("Agent executor is closed")
            self._emitters[turn_id] = emit
            future = self._futures.get(turn_id)
            if future is None:
                future = Future()
                self._futures[turn_id] = future

        if turn["status"] == "succeeded":
            self._finish_future(turn_id, result=None)
            return future
        if turn["status"] == "canceled":
            self._finish_future(turn_id, canceled=True)
            return future
        if turn["status"] == "failed":
            self._finish_future(
                turn_id,
                error=RuntimeError(turn.get("error") or "Agent turn failed"),
            )
            return future
        if plan is None:
            self._finish_future(
                turn_id,
                error=RuntimeError("Agent turn has no durable Plan"),
            )
            return future

        self.start()
        self._engine.notify()
        return future

    def _emit(self, turn_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            emitter = self._emitters.get(turn_id)
        if emitter is None:
            return
        try:
            emitter(event)
        except Exception:
            # RuntimeTaskEvent already persists structural events. A broken
            # browser connection must never fail or retry the Agent handler.
            return

    def _finish_future(
        self,
        turn_id: str,
        *,
        result: Any = None,
        error: BaseException | None = None,
        canceled: bool = False,
    ) -> None:
        with self._lock:
            future = self._futures.pop(turn_id, None)
            self._emitters.pop(turn_id, None)
        if future is None or future.done():
            return
        if canceled:
            future.cancel()
        elif error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def _mark_turn_failed(
        self,
        context: TaskExecutionContext,
        turn_id: str,
        request_id: str,
        error_text: str,
    ) -> str | None:
        now = time.time()
        with UnitOfWork(self.database) as uow:
            task = uow.session.get(RuntimeTaskRow, context.task["id"])
            if (
                task is None
                or task.status != "running"
                or task.claim_token != context.claim["claim_token"]
                or task.claim_until is None
                or task.claim_until <= now
            ):
                raise ConflictError(
                    "Agent failure finalization lost its RuntimeTask lease"
                )
            turn = uow.agent_turns.get(turn_id)
            if turn["status"] == "canceled":
                raise TaskExecutionCanceled("Agent turn was canceled")
            if turn["status"] == "failed":
                return turn.get("assistant_message_id")
            if turn["status"] == "succeeded":
                return turn.get("assistant_message_id")

            step = uow.agent_turns.add_step(
                turn_id,
                "error",
                arguments={"error": error_text},
                request_id=request_id,
            )
            uow.agent_turns.finish_step(
                step["id"],
                "failed",
                summary=error_text[:120],
                error=error_text,
            )
            uow.agent_turns.set_usage(
                turn_id,
                int(context.usage.get("prompt_tokens") or 0),
                int(context.usage.get("completion_tokens") or 0),
            )
            assistant_message = uow.conversations.add_message(
                turn["conversation_id"],
                "assistant",
                f"执行失败：{error_text}",
            )
            uow.agent_turns.set_messages(
                turn_id,
                assistant_message_id=assistant_message["id"],
            )
            uow.agent_turns.set_status(
                turn_id,
                "failed",
                error=error_text,
            )
            return assistant_message["id"]

    def _mark_turn_canceled(self, turn_id: str) -> None:
        with UnitOfWork(self.database) as uow:
            turn = uow.agent_turns.get(turn_id)
            if turn["status"] == "running":
                uow.agent_turns.set_status(turn_id, "canceled")

    def _handle_turn(
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
        try:
            result = self._runner(
                self.database,
                self.settings,
                self.job_engine,
                context,
                live_emit=lambda event: self._emit(turn_id, event),
                request_id=request_id,
            )
            self._finish_future(turn_id, result=result)
            return result
        except TaskExecutionCanceled:
            self._mark_turn_canceled(turn_id)
            self._finish_future(turn_id, canceled=True)
            raise
        except ConflictError:
            # A newer Attempt, timeout recovery, or cancellation owns state.
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

            message_id = self._mark_turn_failed(
                context,
                turn_id,
                request_id,
                error_text,
            )
            failure_message = f"执行失败：{error_text}"
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
                    "text": failure_message,
                },
            )
            context.emit(
                "agent.done",
                {
                    "turn_id": turn_id,
                    "type": "done",
                    "message_id": message_id,
                    "usage": {
                        "prompt": int(
                            context.usage.get("prompt_tokens") or 0
                        ),
                        "completion": int(
                            context.usage.get("completion_tokens") or 0
                        ),
                    },
                    "canceled": False,
                    "failed": True,
                },
            )
            self._finish_future(
                turn_id,
                error=RuntimeError(error_text),
            )
            raise RuntimeError(error_text) from exc
        finally:
            request_id_var.reset(request_token)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            pending = len(self._futures)
        return {
            "workers": self.workers,
            "max_queued": self.max_queued,
            "pending": pending,
            **self._engine.snapshot(),
        }

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = list(self._futures.values())
            self._futures.clear()
            self._emitters.clear()
        self._engine.shutdown(wait=True)
        for future in futures:
            if not future.done():
                future.cancel()


_executor_lock = threading.Lock()


def get_durable_agent_turn_executor(
    app,
    job_engine,
) -> DurableAgentTurnExecutor:
    """Return one durable Agent executor per FastAPI application."""

    executor = getattr(app.state, "agent_turn_executor", None)
    if executor is not None:
        return executor
    with _executor_lock:
        executor = getattr(app.state, "agent_turn_executor", None)
        if executor is None:
            executor = DurableAgentTurnExecutor(
                app.state.database,
                app.state.settings,
                job_engine,
            )
            app.state.agent_turn_executor = executor
            _register_shutdown(app, executor.shutdown)
    return executor


__all__ = [
    "DurableAgentTurnExecutor",
    "get_durable_agent_turn_executor",
]
