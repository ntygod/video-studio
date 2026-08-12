import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.application.task_runtime import TaskRuntime
from app.store.repositories import ConflictError


def _create_plan(
    app,
    project_id: str,
    tasks: list[dict],
    *,
    key: str,
):
    return TaskRuntime(app.state.database).create_plan(
        project_id=project_id,
        kind="test.workflow",
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        tasks=tasks,
    )


def test_runtime_releases_dependency_graph_in_order(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    plan = _create_plan(
        app,
        project["id"],
        [
            {
                "key": "prepare",
                "type": "test.prepare",
                "payload": {"value": 1},
                "max_attempts": 2,
            },
            {
                "key": "publish",
                "type": "test.publish",
                "depends_on": ["prepare"],
            },
        ],
        key="dependency-order",
    )
    duplicate = _create_plan(
        app,
        project["id"],
        [
            {"key": "ignored", "type": "test.ignored"},
        ],
        key="dependency-order",
    )
    assert duplicate["id"] == plan["id"]
    assert [task["task_key"] for task in duplicate["tasks"]] == [
        "prepare",
        "publish",
    ]

    now = time.time() + 1
    first = runtime.claim_next(
        "worker-a",
        kinds={"test.workflow"},
        now=now,
    )
    assert first is not None
    assert first["task"]["task_key"] == "prepare"
    assert first["attempt"]["attempt"] == 1

    # The second task is visible but cannot be leased before its predecessor.
    assert (
        runtime.claim_next(
            "worker-b",
            kinds={"test.workflow"},
            now=now,
        )
        is None
    )

    runtime.complete(
        first,
        result={"prepared": True},
        now=now + 1,
    )
    second = runtime.claim_next(
        "worker-b",
        kinds={"test.workflow"},
        now=now + 2,
    )
    assert second is not None
    assert second["task"]["task_key"] == "publish"
    runtime.complete(
        second,
        result={"published": True},
        now=now + 3,
    )

    completed = runtime.get_plan(plan["id"])
    assert completed["status"] == "succeeded"
    assert [
        task["status"] for task in completed["tasks"]
    ] == ["succeeded", "succeeded"]
    events = runtime.events(plan["id"])
    assert [event["seq"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert events[-1]["event_type"] == "plan.succeeded"


def test_runtime_claim_is_exclusive_across_workers(
    app,
    project,
):
    plan = _create_plan(
        app,
        project["id"],
        [{"key": "only", "type": "test.only"}],
        key="exclusive-claim",
    )
    runtime = TaskRuntime(app.state.database)
    barrier = Barrier(2)
    now = time.time() + 1

    def claim(worker_id: str):
        barrier.wait()
        return TaskRuntime(app.state.database).claim_next(
            worker_id,
            kinds={"test.workflow"},
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(claim, ["worker-a", "worker-b"])
        )

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    stored = runtime.get_plan(plan["id"])
    task = stored["tasks"][0]
    assert task["status"] == "running"
    assert task["attempt_count"] == 1
    assert len(task["attempts"]) == 1


def test_runtime_recovers_expired_lease_as_new_attempt(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    plan = _create_plan(
        app,
        project["id"],
        [
            {
                "key": "recoverable",
                "type": "test.recoverable",
                "max_attempts": 2,
            }
        ],
        key="lease-recovery",
    )
    now = time.time() + 1
    first = runtime.claim_next(
        "worker-old",
        kinds={"test.workflow"},
        lease_seconds=5,
        now=now,
    )
    assert first is not None

    assert runtime.recover(now=now + 6) == 1
    recovered = runtime.get_plan(plan["id"])
    task = recovered["tasks"][0]
    assert task["status"] == "queued"
    assert task["attempts"][0]["status"] == "interrupted"
    assert task["attempts"][0]["retryable"] is True

    second = runtime.claim_next(
        "worker-new",
        kinds={"test.workflow"},
        lease_seconds=5,
        now=now + 7,
    )
    assert second is not None
    assert second["attempt"]["attempt"] == 2

    with pytest.raises(
        ConflictError,
        match="completion lost its lease",
    ):
        runtime.complete(
            first,
            result={"late": True},
            now=now + 8,
        )

    runtime.complete(
        second,
        result={"ok": True},
        now=now + 9,
    )
    completed = runtime.get_plan(plan["id"])
    assert completed["status"] == "succeeded"
    assert [
        attempt["status"]
        for attempt in completed["tasks"][0]["attempts"]
    ] == ["interrupted", "succeeded"]


def test_runtime_retry_policy_stops_at_max_attempts(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    plan = _create_plan(
        app,
        project["id"],
        [
            {
                "key": "unstable",
                "type": "test.unstable",
                "max_attempts": 2,
            }
        ],
        key="retry-limit",
    )
    now = time.time() + 1
    first = runtime.claim_next(
        "worker-a",
        kinds={"test.workflow"},
        now=now,
    )
    assert first is not None
    after_first = runtime.fail(
        first,
        error="transient",
        retryable=True,
        backoff_seconds=2,
        now=now + 1,
    )
    assert after_first["status"] == "queued"
    assert after_first["available_at"] == pytest.approx(
        now + 3
    )
    assert (
        runtime.claim_next(
            "worker-b",
            kinds={"test.workflow"},
            now=now + 2,
        )
        is None
    )

    second = runtime.claim_next(
        "worker-b",
        kinds={"test.workflow"},
        now=now + 3,
    )
    assert second is not None
    exhausted = runtime.fail(
        second,
        error="still broken",
        retryable=True,
        now=now + 4,
    )
    assert exhausted["status"] == "failed"

    failed = runtime.get_plan(plan["id"])
    assert failed["status"] == "failed"
    assert [
        attempt["retryable"]
        for attempt in failed["tasks"][0]["attempts"]
    ] == [True, False]
    assert (
        runtime.claim_next(
            "worker-c",
            kinds={"test.workflow"},
            now=now + 5,
        )
        is None
    )


def test_runtime_timeout_and_cancel_invalidate_old_claims(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    timed_plan = _create_plan(
        app,
        project["id"],
        [
            {
                "key": "timed",
                "type": "test.timed",
                "max_attempts": 1,
                "timeout_seconds": 3,
            }
        ],
        key="timeout",
    )
    now = time.time() + 1
    timed_claim = runtime.claim_next(
        "worker-timeout",
        kinds={"test.workflow"},
        lease_seconds=30,
        now=now,
    )
    assert timed_claim is not None
    assert runtime.recover(now=now + 4) == 1
    timed = runtime.get_plan(timed_plan["id"])
    assert timed["status"] == "failed"
    assert timed["tasks"][0]["attempts"][0]["status"] == (
        "timed_out"
    )

    canceled_plan = _create_plan(
        app,
        project["id"],
        [{"key": "cancel", "type": "test.cancel"}],
        key="cancel",
    )
    cancel_claim = runtime.claim_next(
        "worker-cancel",
        kinds={"test.workflow"},
        now=now + 5,
    )
    assert cancel_claim is not None
    canceled = runtime.cancel(
        canceled_plan["id"],
        reason="user canceled",
        now=now + 6,
    )
    assert canceled["status"] == "canceled"
    assert canceled["tasks"][0]["status"] == "canceled"
    assert canceled["tasks"][0]["attempts"][0]["status"] == (
        "canceled"
    )
    with pytest.raises(
        ConflictError,
        match="completion lost its lease",
    ):
        runtime.complete(
            cancel_claim,
            result={"late": True},
            now=now + 7,
        )


def test_runtime_rejects_invalid_dependency_graph(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with pytest.raises(
        ValueError,
        match="dependency is not defined",
    ):
        runtime.create_plan(
            project_id=project["id"],
            kind="test.invalid",
            tasks=[
                {
                    "key": "a",
                    "type": "test.a",
                    "depends_on": ["missing"],
                }
            ],
        )

    with pytest.raises(ValueError, match="contains a cycle"):
        runtime.create_plan(
            project_id=project["id"],
            kind="test.invalid",
            tasks=[
                {
                    "key": "a",
                    "type": "test.a",
                    "depends_on": ["b"],
                },
                {
                    "key": "b",
                    "type": "test.b",
                    "depends_on": ["a"],
                },
            ],
        )
