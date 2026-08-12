"""Worker and handler registry for the generic durable task runtime."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from app.application.task_runtime import TaskRuntime
from app.store.repositories import ConflictError

TaskHandler = Callable[["TaskExecutionContext"], dict[str, Any] | None]


class RetryableTaskError(RuntimeError):
    """A handler failed before its retry-safe boundary."""

    def __init__(
        self,
        message: str,
        *,
        backoff_seconds: float = 0.0,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.checkpoint = checkpoint
        self.usage = usage


class TaskExecutionCanceled(RuntimeError):
    """Cooperative handler cancellation."""


@dataclass(slots=True)
class TaskExecutionContext:
    runtime: TaskRuntime
    claim: dict[str, Any]
    lease_seconds: float
    _lease_lost: threading.Event
    checkpoint: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_claim(
        cls,
        runtime: TaskRuntime,
        claim: dict[str, Any],
        lease_seconds: float,
        lease_lost: threading.Event,
    ) -> "TaskExecutionContext":
        return cls(
            runtime=runtime,
            claim=claim,
            lease_seconds=lease_seconds,
            _lease_lost=lease_lost,
            checkpoint=dict(claim["task"].get("checkpoint") or {}),
            usage=dict(claim["task"].get("usage") or {}),
        )

    @property
    def plan(self) -> dict[str, Any]:
        return self.claim["plan"]

    @property
    def task(self) -> dict[str, Any]:
        return self.claim["task"]

    @property
    def attempt(self) -> dict[str, Any]:
        return self.claim["attempt"]

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def heartbeat(
        self,
        *,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if checkpoint is not None:
            self.checkpoint = dict(checkpoint)
        if usage is not None:
            self.usage = dict(usage)
        try:
            return self.runtime.heartbeat(
                self.claim,
                lease_seconds=self.lease_seconds,
                checkpoint=self.checkpoint,
                usage=self.usage,
            )
        except ConflictError:
            self._lease_lost.set()
            raise

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.lease_lost:
            raise ConflictError("runtime task lease is no longer owned")
        return self.runtime.append_event(
            self.plan["id"],
            event_type,
            task_id=self.task["id"],
            attempt_id=self.attempt["id"],
            payload=payload,
        )

    def cancellation_requested(self) -> bool:
        if self.lease_lost:
            return True
        try:
            plan = self.runtime.get_plan(self.plan["id"])
            task = self.runtime.get_task(self.task["id"])
        except Exception:
            return True
        return bool(
            plan["status"] == "canceled"
            or task["cancel_requested"]
            or task["status"] != "running"
            or task["claim_owner"] != self.task["claim_owner"]
            or task["claim_attempt"] != self.task["claim_attempt"]
        )

    def raise_if_cancelled(self) -> None:
        if self.cancellation_requested():
            raise TaskExecutionCanceled("runtime task was canceled")


class TaskRuntimeEngine:
    """Fixed worker pool for one non-overlapping set of Plan kinds."""

    def __init__(
        self,
        database,
        *,
        kinds: Iterable[str],
        workers: int = 2,
        lease_seconds: float = 60.0,
        heartbeat_interval: float = 15.0,
        recovery_interval: float = 5.0,
        engine_id: str | None = None,
    ):
        normalized_kinds = frozenset(
            str(kind).strip() for kind in kinds if str(kind).strip()
        )
        if not normalized_kinds:
            raise ValueError("task runtime engine requires at least one kind")
        self.runtime = TaskRuntime(database)
        self.kinds = normalized_kinds
        self.workers = max(1, min(int(workers), 32))
        self.lease_seconds = max(2.0, float(lease_seconds))
        self.heartbeat_interval = max(
            0.25,
            min(float(heartbeat_interval), self.lease_seconds / 2),
        )
        self.recovery_interval = max(0.25, float(recovery_interval))
        self.engine_id = engine_id or f"runtime-{uuid.uuid4().hex[:12]}"
        self._handlers: dict[str, TaskHandler] = {}
        self._handlers_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Condition()
        self._started = False
        self._start_lock = threading.Lock()
        self._worker_threads: list[threading.Thread] = []
        self._reaper_thread: threading.Thread | None = None

    def register(
        self,
        task_type: str,
        handler: TaskHandler,
    ) -> None:
        normalized = str(task_type or "").strip()
        if not normalized:
            raise ValueError("runtime task handler type is required")
        with self._handlers_lock:
            if normalized in self._handlers:
                raise ValueError(
                    f"runtime task handler already registered: {normalized}"
                )
            self._handlers[normalized] = handler
        self.notify()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            if self._stop.is_set():
                raise RuntimeError("task runtime engine has been stopped")
            self.runtime.recover(kinds=self.kinds)
            self._worker_threads = [
                threading.Thread(
                    target=self._worker_loop,
                    args=(index,),
                    name=f"{self.engine_id}-worker-{index}",
                    daemon=True,
                )
                for index in range(self.workers)
            ]
            for thread in self._worker_threads:
                thread.start()
            self._reaper_thread = threading.Thread(
                target=self._reaper_loop,
                name=f"{self.engine_id}-reaper",
                daemon=True,
            )
            self._reaper_thread.start()
            self._started = True

    def notify(self) -> None:
        with self._wake:
            self._wake.notify_all()

    def shutdown(self, *, wait: bool = True) -> None:
        self._stop.set()
        self.notify()
        if not wait:
            return
        for thread in self._worker_threads:
            thread.join(timeout=5)
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)

    def snapshot(self) -> dict[str, Any]:
        with self._handlers_lock:
            handlers = sorted(self._handlers)
        return {
            "engine_id": self.engine_id,
            "kinds": sorted(self.kinds),
            "handlers": handlers,
            "workers": self.workers,
            "started": self._started,
            "stopped": self._stop.is_set(),
            "live_workers": sum(
                1 for thread in self._worker_threads if thread.is_alive()
            ),
        }

    def _handler(self, task_type: str) -> TaskHandler | None:
        with self._handlers_lock:
            return self._handlers.get(task_type)

    def _worker_loop(self, index: int) -> None:
        worker_id = f"{self.engine_id}:worker:{index}"
        while not self._stop.is_set():
            try:
                claim = self.runtime.claim_next(
                    worker_id,
                    kinds=self.kinds,
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                claim = None
            if claim is None:
                with self._wake:
                    self._wake.wait(timeout=0.5)
                continue
            try:
                self._execute_claim(claim)
            except Exception:
                # Claim state is reconciled by fail/complete or the reaper.
                # A malformed task must not terminate the worker process.
                continue

    def _reaper_loop(self) -> None:
        while not self._stop.wait(self.recovery_interval):
            try:
                recovered = self.runtime.recover(kinds=self.kinds)
            except Exception:
                recovered = 0
            if recovered:
                self.notify()

    def _heartbeat_loop(
        self,
        context: TaskExecutionContext,
        done: threading.Event,
    ) -> None:
        while not done.wait(self.heartbeat_interval):
            if self._stop.is_set():
                return
            try:
                context.heartbeat()
            except Exception:
                context._lease_lost.set()
                return

    def _safe_fail(
        self,
        claim: dict[str, Any],
        *,
        error: str,
        retryable: bool,
        backoff_seconds: float = 0.0,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        try:
            task = self.runtime.fail(
                claim,
                error=error,
                retryable=retryable,
                backoff_seconds=backoff_seconds,
                checkpoint=checkpoint,
                usage=usage,
            )
            if task["status"] == "queued":
                self.notify()
        except ConflictError:
            return

    def _execute_claim(self, claim: dict[str, Any]) -> None:
        task = claim["task"]
        handler = self._handler(task["task_type"])
        if handler is None:
            self._safe_fail(
                claim,
                error=(
                    "no runtime task handler registered for "
                    + task["task_type"]
                ),
                retryable=False,
            )
            return

        lease_lost = threading.Event()
        context = TaskExecutionContext.from_claim(
            self.runtime,
            claim,
            self.lease_seconds,
            lease_lost,
        )
        heartbeat_done = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(context, heartbeat_done),
            name=f"{self.engine_id}-heartbeat-{task['id'][:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            result = handler(context)
            if result is not None and not isinstance(result, dict):
                raise TypeError("runtime task handler must return a mapping")
            context.raise_if_cancelled()
            if context.lease_lost:
                return
            self.runtime.complete(
                claim,
                result=result or {},
                checkpoint=context.checkpoint,
                usage=context.usage,
            )
            self.notify()
        except RetryableTaskError as exc:
            self._safe_fail(
                claim,
                error=str(exc),
                retryable=True,
                backoff_seconds=exc.backoff_seconds,
                checkpoint=(
                    exc.checkpoint
                    if exc.checkpoint is not None
                    else context.checkpoint
                ),
                usage=(
                    exc.usage
                    if exc.usage is not None
                    else context.usage
                ),
            )
        except TaskExecutionCanceled:
            try:
                self.runtime.cancel(
                    claim["plan"]["id"],
                    reason="runtime task canceled during execution",
                )
            except ConflictError:
                pass
        except ConflictError:
            # Timeout, cancellation, or lease recovery already owns state.
            return
        except Exception as exc:
            policy = dict(task.get("policy") or {})
            self._safe_fail(
                claim,
                error=str(exc),
                retryable=bool(policy.get("retry_unhandled", False)),
                backoff_seconds=float(
                    policy.get("retry_backoff_seconds") or 0.0
                ),
                checkpoint=context.checkpoint,
                usage=context.usage,
            )
        finally:
            heartbeat_done.set()
            heartbeat.join(timeout=2)


__all__ = [
    "RetryableTaskError",
    "TaskExecutionCanceled",
    "TaskExecutionContext",
    "TaskRuntimeEngine",
]
