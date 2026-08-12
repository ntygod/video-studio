import time

from app.application.task_runtime import TaskRuntime
from app.application.task_runtime_engine import (
    RetryableTaskError,
    TaskRuntimeEngine,
)


def _wait_plan(runtime: TaskRuntime, plan_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        plan = runtime.get_plan(plan_id)
        if plan["status"] in {
            "succeeded",
            "failed",
            "blocked",
            "canceled",
        }:
            return plan
        time.sleep(0.02)
    raise AssertionError(f"runtime plan did not finish: {plan}")


def test_runtime_engine_executes_registered_dependency_graph(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    order: list[str] = []
    engine = TaskRuntimeEngine(
        app.state.database,
        kinds={"engine.workflow"},
        workers=2,
        lease_seconds=3,
        heartbeat_interval=0.25,
        recovery_interval=0.25,
        engine_id="engine-test",
    )

    def prepare(context):
        order.append("prepare")
        context.heartbeat(
            checkpoint={"phase": "prepared"},
            usage={"units": 1},
        )
        context.emit("test.prepared", {"ok": True})
        return {"prepared": True}

    def publish(context):
        order.append("publish")
        return {
            "upstream_task_id": context.task[
                "depends_on_task_ids"
            ][0]
        }

    engine.register("engine.prepare", prepare)
    engine.register("engine.publish", publish)
    engine.start()
    try:
        plan = runtime.create_plan(
            project_id=project["id"],
            kind="engine.workflow",
            idempotency_key="engine-dependency",
            tasks=[
                {
                    "key": "prepare",
                    "type": "engine.prepare",
                },
                {
                    "key": "publish",
                    "type": "engine.publish",
                    "depends_on": ["prepare"],
                },
            ],
        )
        engine.notify()
        completed = _wait_plan(runtime, plan["id"])
    finally:
        engine.shutdown()

    assert completed["status"] == "succeeded"
    assert order == ["prepare", "publish"]
    assert completed["tasks"][0]["checkpoint"] == {
        "phase": "prepared"
    }
    assert completed["tasks"][0]["usage"] == {"units": 1}
    assert any(
        event["event_type"] == "test.prepared"
        for event in runtime.events(plan["id"])
    )
    assert engine.snapshot()["live_workers"] == 0


def test_runtime_engine_retries_only_explicit_retryable_error(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    calls = {"count": 0}
    engine = TaskRuntimeEngine(
        app.state.database,
        kinds={"engine.retry"},
        workers=1,
        lease_seconds=3,
        heartbeat_interval=0.25,
        recovery_interval=0.25,
        engine_id="engine-retry",
    )

    def unstable(context):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RetryableTaskError(
                "temporary outage",
                checkpoint={"completed_stage": 1},
            )
        assert context.checkpoint == {"completed_stage": 1}
        return {"ok": True}

    engine.register("engine.unstable", unstable)
    engine.start()
    try:
        plan = runtime.create_plan(
            project_id=project["id"],
            kind="engine.retry",
            idempotency_key="engine-retry",
            tasks=[
                {
                    "key": "unstable",
                    "type": "engine.unstable",
                    "max_attempts": 2,
                }
            ],
        )
        engine.notify()
        completed = _wait_plan(runtime, plan["id"])
    finally:
        engine.shutdown()

    assert completed["status"] == "succeeded"
    assert calls["count"] == 2
    attempts = completed["tasks"][0]["attempts"]
    assert [attempt["status"] for attempt in attempts] == [
        "failed",
        "succeeded",
    ]
    assert attempts[0]["retryable"] is True


def test_runtime_engine_fails_closed_for_unknown_or_unhandled_tasks(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    engine = TaskRuntimeEngine(
        app.state.database,
        kinds={"engine.closed"},
        workers=1,
        lease_seconds=3,
        heartbeat_interval=0.25,
        recovery_interval=0.25,
        engine_id="engine-closed",
    )

    def broken(_context):
        raise RuntimeError("unsafe handler failure")

    engine.register("engine.broken", broken)
    engine.start()
    try:
        unknown = runtime.create_plan(
            project_id=project["id"],
            kind="engine.closed",
            idempotency_key="engine-unknown",
            tasks=[
                {
                    "key": "unknown",
                    "type": "engine.unknown",
                    "max_attempts": 3,
                }
            ],
        )
        engine.notify()
        unknown_result = _wait_plan(runtime, unknown["id"])

        broken_plan = runtime.create_plan(
            project_id=project["id"],
            kind="engine.closed",
            idempotency_key="engine-broken",
            tasks=[
                {
                    "key": "broken",
                    "type": "engine.broken",
                    "max_attempts": 3,
                }
            ],
        )
        engine.notify()
        broken_result = _wait_plan(runtime, broken_plan["id"])
    finally:
        engine.shutdown()

    assert unknown_result["status"] == "failed"
    assert "no runtime task handler" in unknown_result["tasks"][0][
        "error"
    ]
    assert len(unknown_result["tasks"][0]["attempts"]) == 1

    assert broken_result["status"] == "failed"
    assert broken_result["tasks"][0]["error"] == (
        "unsafe handler failure"
    )
    assert len(broken_result["tasks"][0]["attempts"]) == 1
