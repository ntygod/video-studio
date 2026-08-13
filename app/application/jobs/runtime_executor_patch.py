"""Install RuntimeTask ownership for image, video, and TTS Jobs."""

from __future__ import annotations

import threading
from typing import Any

from app.api.logging import request_id_var
from app.application.reconciled_task_runtime import ReconciledTaskRuntime
from app.application.regeneration_plan_service import advance_plan_for_job
from app.application.runtime_governance import (
    bind_runtime_execution,
    reset_runtime_execution,
)
from app.application.task_runtime_engine import (
    RetryableTaskError,
    TaskExecutionCanceled,
    TaskExecutionContext,
    TaskRuntimeEngine,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError

from .context import JobContext
from .engine import JobCanceled, JobEngine
from .runtime_contract import (
    MEDIA_JOB_TASK_TYPE,
    RUNTIME_JOB_PLAN_KINDS,
    TTS_JOB_TASK_TYPE,
    VOICE_JOB_TASK_TYPE,
)

_INSTALLED = False
_TERMINAL_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "canceled"}
)


def _advance_parent(engine: JobEngine, job_id: str) -> None:
    try:
        advance_plan_for_job(engine.database, job_id, engine)
    except Exception:
        # RegenerationPlan has its own durable recovery loop.
        return


def _runtime_job_current(
    job: dict[str, Any],
    context: TaskExecutionContext,
    generation: int,
) -> bool:
    return bool(
        job.get("runtime_plan_id") == context.plan["id"]
        and job.get("runtime_task_id") == context.task["id"]
        and int(job.get("runtime_generation") or 1) == generation
    )


def _execute_runtime_job(
    engine: JobEngine,
    context: TaskExecutionContext,
) -> dict[str, Any]:
    payload = dict(context.task.get("payload") or {})
    job_id = str(payload.get("job_id") or "")
    generation = max(1, int(payload.get("runtime_generation") or 1))
    if not job_id:
        raise RuntimeError("Runtime media Task has no job_id")

    with UnitOfWork(engine.database) as uow:
        job = uow.jobs.get(job_id)
        if not _runtime_job_current(job, context, generation):
            raise ConflictError(
                "Runtime media Task is no longer the current Job execution"
            )
        if job["status"] == "succeeded":
            return {
                "job_id": job_id,
                "result": job.get("result") or {},
                "replayed": True,
            }
        if job["status"] == "canceled" or job["cancel_requested"]:
            if job["status"] != "canceled":
                uow.jobs.update_state(job_id, "canceled")
            raise TaskExecutionCanceled("Job was canceled before execution")
        job = uow.jobs.begin_runtime_attempt(
            job_id,
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            generation=generation,
            attempt=int(context.attempt["attempt"]),
            worker_id=str(context.task.get("claim_owner") or "runtime"),
        )
        uow.jobs.add_event(
            job_id,
            "任务开始执行",
            stage="start",
            progress=0.0,
        )

    cancel_event = threading.Event()
    with engine._lock:
        engine._cancel_events[job_id] = cancel_event

    def should_cancel() -> bool:
        if cancel_event.is_set() or context.cancellation_requested():
            return True
        try:
            with UnitOfWork(engine.database) as uow:
                current = uow.jobs.get(job_id)
            return bool(
                current["cancel_requested"]
                or not _runtime_job_current(
                    current,
                    context,
                    generation,
                )
            )
        except Exception:
            return True

    request_token = request_id_var.set(
        str((job.get("payload") or {}).get("_request_id") or "")
    )
    runtime_token = bind_runtime_execution(
        context,
        turn_id=str(job.get("turn_id") or ""),
    )
    try:
        if should_cancel():
            raise JobCanceled()
        handler = engine._handler_for(job)
        handler(
            JobContext(
                engine.database,
                engine.settings,
                engine.media_store,
                job,
                should_cancel,
            )
        )
        if should_cancel():
            raise JobCanceled()
        with UnitOfWork(engine.database) as uow:
            current = uow.jobs.get(job_id)
            if not _runtime_job_current(current, context, generation):
                raise ConflictError(
                    "Job execution changed before completion"
                )
            uow.jobs.add_event(
                job_id,
                "任务执行完成",
                stage="end",
                progress=1.0,
            )
            uow.jobs.update_state(
                job_id,
                "succeeded",
                progress=1.0,
            )
            completed = uow.jobs.get(job_id)
        _advance_parent(engine, job_id)
        context.checkpoint = {
            "job_id": job_id,
            "runtime_generation": generation,
            "status": "succeeded",
        }
        return {
            "job_id": job_id,
            "result": completed.get("result") or {},
            "replayed": False,
        }
    except JobCanceled:
        with UnitOfWork(engine.database) as uow:
            current = uow.jobs.get(job_id)
            if _runtime_job_current(current, context, generation):
                if current["status"] != "canceled":
                    uow.jobs.add_event(
                        job_id,
                        "任务已取消",
                        level="warning",
                        stage="cancel",
                    )
                    uow.jobs.update_state(job_id, "canceled")
        _advance_parent(engine, job_id)
        raise TaskExecutionCanceled("Job was canceled") from None
    except ConflictError:
        raise
    except Exception as exc:
        attempt = int(context.attempt["attempt"])
        max_attempts = int(context.task.get("max_attempts") or 1)
        retryable = attempt < max_attempts
        with UnitOfWork(engine.database) as uow:
            current = uow.jobs.get(job_id)
            if not _runtime_job_current(current, context, generation):
                raise ConflictError(
                    "Job execution changed while handling a failure"
                ) from exc
            if retryable:
                uow.jobs.update_state(
                    job_id,
                    "queued",
                    progress=0.0,
                    error="",
                )
                uow.jobs.add_event(
                    job_id,
                    f"任务失败，将重试：{exc}",
                    level="error",
                    stage="error",
                )
            else:
                uow.jobs.update_state(
                    job_id,
                    "failed",
                    error=str(exc),
                )
                uow.jobs.add_event(
                    job_id,
                    f"任务失败：{exc}",
                    level="error",
                    stage="error",
                )
        if retryable:
            raise RetryableTaskError(
                str(exc),
                backoff_seconds=min(2 ** attempt, 60),
                checkpoint={
                    "job_id": job_id,
                    "runtime_generation": generation,
                    "last_error": str(exc),
                },
            ) from exc
        _advance_parent(engine, job_id)
        raise RuntimeError(str(exc)) from exc
    finally:
        reset_runtime_execution(runtime_token)
        request_id_var.reset(request_token)
        with engine._lock:
            engine._cancel_events.pop(job_id, None)


def install_runtime_job_executor() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_init = JobEngine.__init__
    original_start = JobEngine.start
    original_stop = JobEngine.stop
    original_submit = JobEngine.submit
    original_cancel = JobEngine.cancel
    original_recover = JobEngine.recover

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._durable_job_engine = TaskRuntimeEngine(
            self.database,
            kinds=RUNTIME_JOB_PLAN_KINDS,
            workers=max(1, min(self._workers_count, 4)),
            lease_seconds=90,
            heartbeat_interval=15,
            recovery_interval=5,
            engine_id="media-job-runtime",
        )
        self._durable_job_engine.runtime = ReconciledTaskRuntime(
            self.database
        )
        self._durable_job_engine.register(
            MEDIA_JOB_TASK_TYPE,
            lambda context: _execute_runtime_job(self, context),
        )
        self._durable_job_engine.register(
            TTS_JOB_TASK_TYPE,
            lambda context: _execute_runtime_job(self, context),
        )
        self._durable_job_engine.register(
            VOICE_JOB_TASK_TYPE,
            lambda context: _execute_runtime_job(self, context),
        )

    def patched_start(self):
        self._durable_job_engine.start()
        return original_start(self)

    def patched_stop(self, timeout: float = 10):
        self._durable_job_engine.shutdown(wait=True)
        return original_stop(self, timeout=timeout)

    def patched_submit(self, job_id: str) -> None:
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
        if job.get("runtime_plan_id"):
            if job["status"] in _TERMINAL_JOB_STATUSES:
                return
            self._durable_job_engine.notify()
            return
        return original_submit(self, job_id)

    def patched_cancel(self, job_id: str) -> None:
        original_cancel(self, job_id)
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
        plan_id = str(job.get("runtime_plan_id") or "")
        if not plan_id:
            return
        try:
            self._durable_job_engine.runtime.cancel(
                plan_id,
                reason="Job cancellation requested",
            )
        except ConflictError:
            pass
        with UnitOfWork(self.database) as uow:
            current = uow.jobs.get(job_id)
            if current["status"] not in _TERMINAL_JOB_STATUSES:
                uow.jobs.add_event(
                    job_id,
                    "任务已取消",
                    level="warning",
                    stage="cancel",
                )
                uow.jobs.update_state(job_id, "canceled")
        _advance_parent(self, job_id)

    def patched_recover(self) -> int:
        recovered = int(original_recover(self) or 0)
        durable = self._durable_job_engine.runtime.recover(
            kinds=RUNTIME_JOB_PLAN_KINDS,
        )
        if durable:
            self._durable_job_engine.notify()
        return recovered + int(durable or 0)

    JobEngine.__init__ = patched_init
    JobEngine.start = patched_start
    JobEngine.stop = patched_stop
    JobEngine.submit = patched_submit
    JobEngine.cancel = patched_cancel
    JobEngine.recover = patched_recover


__all__ = ["install_runtime_job_executor"]
