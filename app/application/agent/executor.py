"""固定并发与有界排队的 Agent 回合执行器。

Agent 回合仍沿用现有 ``run_turn``，但不再为每个请求创建一个裸线程。执行器使用
固定数量的 daemon worker 和总容量信号量，限制同时运行与排队的回合数量；过载
会变成可观察、可解释的 429，而不是耗尽线程和 SQLite 写锁。
"""

from __future__ import annotations

import queue
import threading
import weakref
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from app.api.logging import request_id_var

from .loop import run_turn

DEFAULT_WORKERS = 2
DEFAULT_MAX_QUEUED = 8


class AgentQueueFull(RuntimeError):
    """Agent 执行池没有剩余运行或排队容量。"""


@dataclass(slots=True)
class _TurnTask:
    turn_id: str
    emit: Callable[[dict[str, Any]], None]
    request_id: str
    future: Future


class AgentTurnExecutor:
    def __init__(
        self,
        database,
        settings,
        job_engine,
        *,
        workers: int = DEFAULT_WORKERS,
        max_queued: int = DEFAULT_MAX_QUEUED,
        runner: Callable[..., None] = run_turn,
    ):
        self.database = database
        self.settings = settings
        self.job_engine = job_engine
        self.workers = max(1, int(workers))
        self.max_queued = max(0, int(max_queued))
        self._runner = runner
        self._capacity = threading.BoundedSemaphore(self.workers + self.max_queued)
        self._queue: queue.Queue[_TurnTask | None] = queue.Queue()
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._worker_threads: list[threading.Thread] = []

        for index in range(self.workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"agent-turn-{index}",
                daemon=True,
            )
            thread.start()
            self._worker_threads.append(thread)

    def submit(
        self,
        turn_id: str,
        emit: Callable[[dict[str, Any]], None],
        *,
        request_id: str = "",
    ) -> Future:
        """提交一个回合；重复 turn_id 返回原 Future，过载时立即拒绝。"""

        with self._lock:
            existing = self._futures.get(turn_id)
            if existing is not None:
                return existing
            if self._closed:
                raise RuntimeError("Agent executor is closed")
            if not self._capacity.acquire(blocking=False):
                raise AgentQueueFull("Agent 执行队列已满")

            future: Future = Future()
            self._futures[turn_id] = future
            self._queue.put_nowait(
                _TurnTask(
                    turn_id=turn_id,
                    emit=emit,
                    request_id=request_id,
                    future=future,
                )
            )
            return future

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                if not task.future.set_running_or_notify_cancel():
                    self._finished(task.turn_id, task.future)
                    continue
                try:
                    self._run(task)
                except BaseException as exc:
                    task.future.set_exception(exc)
                else:
                    task.future.set_result(None)
                finally:
                    self._finished(task.turn_id, task.future)
            finally:
                self._queue.task_done()

    def _run(self, task: _TurnTask) -> None:
        request_id_var.set(task.request_id)
        self._runner(
            self.database,
            self.settings,
            self.job_engine,
            task.turn_id,
            task.emit,
            request_id=task.request_id,
        )

    def _finished(self, turn_id: str, future: Future) -> None:
        released = False
        with self._lock:
            if self._futures.get(turn_id) is future:
                self._futures.pop(turn_id, None)
                released = True
        if released:
            self._capacity.release()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            pending = len(self._futures)
        return {
            "workers": self.workers,
            "max_queued": self.max_queued,
            "pending": pending,
        }

    def shutdown(self) -> None:
        """停止接收新回合，取消尚未开始的任务；运行中任务由 daemon worker 收尾。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True

        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if task is not None:
                    task.future.cancel()
                    self._finished(task.turn_id, task.future)
            finally:
                self._queue.task_done()

        for _ in self._worker_threads:
            self._queue.put_nowait(None)


_executor_lock = threading.Lock()


def _register_shutdown(app, callback: Callable[[], None]) -> None:
    """兼容新旧 FastAPI/Starlette 的生命周期注册 API。

    新版 FastAPI 已移除 ``FastAPI.add_event_handler``，但部分旧版本仍只暴露
    该入口。优先使用 Router API；如果运行时不提供事件注册能力，则至少通过
    weakref finalizer 在 app 被回收时关闭 daemon worker。
    """

    router = getattr(app, "router", None)
    for owner in (router, app):
        add_handler = getattr(owner, "add_event_handler", None)
        if not callable(add_handler):
            continue
        try:
            add_handler("shutdown", callback)
            return
        except (AttributeError, RuntimeError):
            continue

    shutdown_handlers = getattr(router, "on_shutdown", None)
    if hasattr(shutdown_handlers, "append"):
        shutdown_handlers.append(callback)
        return

    weakref.finalize(app, callback)


def get_agent_turn_executor(app, job_engine) -> AgentTurnExecutor:
    """每个 FastAPI app 只创建一个执行池，测试 app 之间互不共享。"""

    executor = getattr(app.state, "agent_turn_executor", None)
    if executor is not None:
        return executor

    with _executor_lock:
        executor = getattr(app.state, "agent_turn_executor", None)
        if executor is None:
            executor = AgentTurnExecutor(
                app.state.database,
                app.state.settings,
                job_engine,
            )
            app.state.agent_turn_executor = executor
            _register_shutdown(app, executor.shutdown)
    return executor
