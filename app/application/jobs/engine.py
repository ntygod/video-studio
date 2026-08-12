"""有界工作池 + 协作式取消 + 自动重试的 Job 引擎。"""

import threading
from typing import Any

from app.api.logging import request_id_var
from app.store import UnitOfWork

from . import queue as job_queue
from .context import JobContext


class JobCanceled(RuntimeError):
    pass


HEARTBEAT_SECONDS = 20
REAPER_SECONDS = 30


class JobEngine:
    def __init__(self, database, settings, media_store=None, workers: int = 4):
        self.database = database
        self.settings = settings
        self.media_store = media_store
        self._workers_count = max(1, workers)
        self._worker_threads: list[threading.Thread] = []
        self._reaper: threading.Thread | None = None
        self._heartbeat: threading.Thread | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._cancel_events: dict[str, threading.Event] = {}
        self._running_jobs: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动固定 worker、lease 线程，并恢复持久化计划。"""
        if self._worker_threads:
            return
        for index in range(self._workers_count):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"job-worker-{index}",
                daemon=True,
            )
            thread.start()
            self._worker_threads.append(thread)
        self._reaper = threading.Thread(
            target=self._reaper_loop,
            name="job-lease-reaper",
            daemon=True,
        )
        self._reaper.start()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            name="job-lease-heartbeat",
            daemon=True,
        )
        self._heartbeat.start()
        try:
            self.recover()
        except Exception:
            # Workers and the periodic reaper still provide a later retry.
            pass

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        for thread in self._worker_threads:
            thread.join(timeout=timeout)
        for thread in (self._reaper, self._heartbeat):
            if thread:
                thread.join(timeout=timeout)

    def submit(self, job_id: str) -> None:
        """仅入队并唤醒 worker，不为每个任务创建线程。"""
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            if job["status"] in ("succeeded", "running"):
                return
            uow.jobs.update_state(
                job_id,
                "queued",
                progress=0.0,
                error="",
            )
            uow.jobs.add_event(job_id, "任务已入队", stage="queue")
        with self._cond:
            self._cond.notify_all()

    def cancel(self, job_id: str) -> None:
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()

    def recover(self) -> int:
        recovered = job_queue.recover(self.database)
        from app.application.regeneration_plan_service import (
            recover_regeneration_plans,
        )

        recover_regeneration_plans(self.database, self)
        return recovered

    def _worker_loop(self) -> None:
        worker_id = f"worker-{threading.get_ident():x}"
        while not self._stop.is_set():
            job = job_queue.claim(self.database, worker_id)
            if job is None:
                with self._cond:
                    self._cond.wait(timeout=1.0)
                continue
            self._run(job)

    def _reaper_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.recover()
            except Exception:
                pass
            self._stop.wait(REAPER_SECONDS)

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    job_ids = list(self._running_jobs)
                job_queue.renew(self.database, job_ids)
            except Exception:
                pass
            self._stop.wait(HEARTBEAT_SECONDS)

    def _run(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        request_id_var.set(
            (job.get("payload") or {}).get("_request_id") or ""
        )
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
            self._running_jobs.add(job_id)

        def should_cancel() -> bool:
            if cancel_event.is_set():
                return True
            try:
                with UnitOfWork(self.database) as uow:
                    return bool(
                        uow.jobs.get(job_id)["cancel_requested"]
                    )
            except Exception:
                return False

        try:
            with UnitOfWork(self.database) as uow:
                uow.jobs.update_state(
                    job_id,
                    "running",
                    progress=0.0,
                )
                uow.jobs.add_event(
                    job_id,
                    "任务开始执行",
                    stage="start",
                )
            if should_cancel():
                raise JobCanceled()
            handler = self._handler_for(job)
            handler(
                JobContext(
                    self.database,
                    self.settings,
                    self.media_store,
                    job,
                    should_cancel,
                )
            )
            if should_cancel():
                raise JobCanceled()
            with UnitOfWork(self.database) as uow:
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
        except JobCanceled:
            with UnitOfWork(self.database) as uow:
                uow.jobs.add_event(
                    job_id,
                    "任务已取消",
                    level="warning",
                    stage="cancel",
                )
                uow.jobs.update_state(job_id, "canceled")
        except Exception as exc:
            attempt = int(job.get("attempt") or 0)
            max_attempts = int(job.get("max_attempts") or 3)
            if attempt < max_attempts:
                with UnitOfWork(self.database) as uow:
                    uow.jobs.add_event(
                        job_id,
                        f"任务失败，将重试：{exc}",
                        level="error",
                        stage="error",
                    )
                    uow.jobs.update_state(
                        job_id,
                        "queued",
                        progress=0.0,
                        error="",
                    )
                job_queue.mark_backoff(
                    self.database,
                    job_id,
                    2 ** attempt,
                )
                with self._cond:
                    self._cond.notify_all()
            else:
                with UnitOfWork(self.database) as uow:
                    uow.jobs.add_event(
                        job_id,
                        f"任务失败：{exc}",
                        level="error",
                        stage="error",
                    )
                    uow.jobs.update_state(
                        job_id,
                        "failed",
                        error=str(exc),
                    )
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._running_jobs.discard(job_id)
            try:
                from app.application.regeneration_plan_service import (
                    advance_plan_for_job,
                )

                advance_plan_for_job(self.database, job_id, self)
            except Exception:
                # The durable plan remains running and the reaper retries it.
                pass
            with self._cond:
                self._cond.notify_all()

    @staticmethod
    def _handler_for(job: dict[str, Any]):
        from . import handlers

        payload = job.get("payload") or {}
        job_type = job["job_type"]
        capability = payload.get("capability") or "llm"
        if job_type == "voice_synthesis":
            return handlers.voice.run
        if job_type == "render":
            return handlers.render.run
        if job_type == "batch":
            return handlers.batch.run
        if job_type == "summary":
            return handlers.summary.run
        if job_type == "llm" or capability == "llm":
            return handlers.llm.run
        if capability in ("image", "video"):
            return handlers.media.run
        if capability == "tts" or job_type == "tts":
            return handlers.tts.run
        raise ValueError(f"unknown job type: {job_type}")


def get_job_engine(app) -> JobEngine:
    engine = getattr(app.state, "job_engine", None)
    if engine is None:
        engine = JobEngine(
            app.state.database,
            app.state.settings,
            app.state.media_store,
        )
        engine.start()
        app.state.job_engine = engine
    return engine
