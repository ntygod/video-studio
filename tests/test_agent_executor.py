import threading
import time

import pytest

from app.application.agent.executor import (
    AgentQueueFull,
    AgentTurnExecutor,
)


def test_agent_executor_bounds_running_and_queued_turns():
    release = threading.Event()
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def runner(_database, _settings, _job_engine, _turn_id, _emit, **_kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            release.wait(timeout=3)
        finally:
            with lock:
                state["active"] -= 1

    executor = AgentTurnExecutor(
        object(),
        object(),
        object(),
        workers=2,
        max_queued=1,
        runner=runner,
    )
    try:
        futures = [
            executor.submit(f"turn-{index}", lambda _event: None)
            for index in range(3)
        ]
        with pytest.raises(AgentQueueFull):
            executor.submit("turn-overflow", lambda _event: None)

        deadline = time.monotonic() + 2
        while state["max_active"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert state["max_active"] == 2

        release.set()
        for future in futures:
            future.result(timeout=3)
        assert executor.snapshot()["pending"] == 0
    finally:
        release.set()
        executor.shutdown()


def test_agent_executor_deduplicates_turn_id():
    release = threading.Event()
    calls = []

    def runner(_database, _settings, _job_engine, turn_id, _emit, **_kwargs):
        calls.append(turn_id)
        release.wait(timeout=2)

    executor = AgentTurnExecutor(
        object(),
        object(),
        object(),
        workers=1,
        max_queued=0,
        runner=runner,
    )
    try:
        first = executor.submit("same-turn", lambda _event: None)
        second = executor.submit("same-turn", lambda _event: None)
        assert first is second
        release.set()
        first.result(timeout=3)
        assert calls == ["same-turn"]
    finally:
        release.set()
        executor.shutdown()
