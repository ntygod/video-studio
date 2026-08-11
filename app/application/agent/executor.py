"""固定并发与有界排队的 Agent 回合执行器。

Agent 回合仍沿用现有 ``run_turn``，但不再为每个请求创建一个裸线程。这个执行器
是迁移到耐久 Task Runtime 前的可靠性边界：限制同时运行和排队的回合数量，并让
过载变成可观察、可解释的 429，而不是耗尽线程和 SQLite 写锁。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from app.api.logging import request_id_var

from .loop import run_turn

DEFAULT_WORKERS = 2
DEFAULT_MAX_QUEUED = 8


class AgentQueueFull(RuntimeError):
    """Agent 执行池没有剩余运行或排队容量。"""


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
        self._pool = ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="agent-turn",
        )
        self._capacity = threading.BoundedSemaphore(self.workers + self.max_queued)
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._closed = False

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
            try:
                future = self._pool.submit(
                    self._run,
                    turn_id,
                    emit,
                    request_id,
                )
            except Exception:
                self._capacity.release()
                raise
            self._futures[turn_id] = future

        future.add_done_callback(
            lambda completed, current_turn_id=turn_id: self._finished(
                current_turn_id, completed
            )
        )
        return future

    def _run(
        self,
        turn_id: str,
        emit: Callable[[dict[str, Any]], None],
        request_id: str,
    ) -> None:
        request_id_var.set(request_id)
        self._runner(
            self.database,
            self.settings,
            self.job_engine,
            turn_id,
            emit,
            request_id=request_id,
        )

    def _finished(self, turn_id: str, future: Future) -> None:
        with self._lock:
            if self._futures.get(turn_id) is future:
                self._futures.pop(turn_id, None)
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
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)


_executor_lock = threading.Lock()


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
            app.add_event_handler("shutdown", executor.shutdown)
    return executor
