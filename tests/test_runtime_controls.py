import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect

from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.task_runtime import TaskRuntime
from app.store import Database, UnitOfWork
from app.store.repositories import ConflictError
from app.store.task_runtime_extensions import RuntimeAdmissionFull


def _task(*, available_at=None):
    definition = {
        "key": "execute",
        "type": AGENT_TASK_TYPE,
        "max_attempts": 1,
    }
    if available_at is not None:
        definition["available_at"] = available_at
    return definition


def _state(database):
    with UnitOfWork(database) as uow:
        return uow.task_runtime.admission_state(AGENT_PLAN_KIND)


def test_agent_admission_rejects_over_capacity_and_cancel_releases(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    first = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="first",
        idempotency_key="admission:first",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    assert _state(app.state.database)["active_count"] == 1

    with pytest.raises(RuntimeAdmissionFull) as rejected:
        runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="test",
            subject_id="second",
            idempotency_key="admission:second",
            tasks=[_task(available_at=time.time() + 3600)],
        )
    assert rejected.value.capacity == 1
    assert rejected.value.active_count == 1

    runtime.cancel(first["id"], reason="release admission test")
    assert _state(app.state.database)["active_count"] == 0

    second = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="second",
        idempotency_key="admission:second",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    assert second["status"] == "queued"
    assert _state(app.state.database)["active_count"] == 1
    runtime.cancel(second["id"], reason="cleanup")


def test_agent_admission_is_exclusive_across_process_transactions(
    app,
    project,
):
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)
    barrier = Barrier(2)

    def create(index: int):
        barrier.wait()
        runtime = TaskRuntime(app.state.database)
        try:
            plan = runtime.create_plan(
                project_id=project["id"],
                kind=AGENT_PLAN_KIND,
                subject_type="test",
                subject_id=f"concurrent-{index}",
                idempotency_key=f"admission:concurrent:{index}",
                tasks=[_task(available_at=time.time() + 3600)],
            )
        except RuntimeAdmissionFull as exc:
            return "rejected", exc.capacity, exc.active_count
        return "accepted", plan["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))

    accepted = [item for item in results if item[0] == "accepted"]
    rejected = [item for item in results if item[0] == "rejected"]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0][1:] == (1, 1)
    state = _state(app.state.database)
    assert state["active_count"] == 1
    TaskRuntime(app.state.database).cancel(
        accepted[0][1],
        reason="cleanup",
    )


def test_admission_capacity_cannot_shrink_below_active_reservations(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 2)
    plans = [
        runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="test",
            subject_id=f"shrink-{index}",
            idempotency_key=f"admission:shrink:{index}",
            tasks=[_task(available_at=time.time() + 3600)],
        )
        for index in range(2)
    ]

    with UnitOfWork(app.state.database) as uow:
        with pytest.raises(ConflictError, match="active reservations: 2"):
            uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    assert _state(app.state.database)["capacity"] == 2
    for plan in plans:
        runtime.cancel(plan["id"], reason="cleanup")


def test_agent_admission_releases_when_plan_succeeds(app, project):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="complete",
        idempotency_key="admission:complete",
        tasks=[_task()],
    )
    claim = runtime.claim_next(
        "admission-worker",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=10,
    )
    assert claim is not None
    runtime.complete(claim, result={"ok": True})

    assert runtime.get_plan(plan["id"])["status"] == "succeeded"
    assert _state(app.state.database)["active_count"] == 0


def test_agent_structural_events_use_semantic_dedupe_identity(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="events",
        idempotency_key="events:dedupe",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    payload = {
        "turn_id": "turn-1",
        "type": "step.start",
        "step_id": "stable-step-1",
        "tool": "write_artifact",
    }
    first = runtime.append_event(
        plan["id"],
        "agent.step.start",
        payload=payload,
    )
    replay = runtime.append_event(
        plan["id"],
        "agent.step.start",
        payload={**payload, "args_preview": "replayed"},
    )

    assert first["id"] == replay["id"]
    assert first["seq"] == replay["seq"]
    assert replay["deduplicated"] is True
    stored = [
        event
        for event in runtime.events(plan["id"])
        if event["event_type"] == "agent.step.start"
        and event["payload"].get("step_id") == "stable-step-1"
    ]
    assert len(stored) == 1
    runtime.cancel(plan["id"], reason="cleanup")


def test_turn_api_returns_429_without_partial_message_when_agent_full(
    app,
    client,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    blocker = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="api-blocker",
        idempotency_key="admission:api-blocker",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "容量拒绝"},
    ).json()

    response = client.post(
        f"/api/conversations/{conversation['id']}/turns",
        json={"content": "这条消息必须整体回滚"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    assert response.json()["capacity"] == 1
    with UnitOfWork(app.state.database) as uow:
        messages = uow.conversations.list_messages(conversation["id"])
    assert messages == []
    runtime.cancel(blocker["id"], reason="cleanup")


def test_fresh_database_installs_runtime_control_tables(tmp_path):
    database = Database(
        f"sqlite:///{(tmp_path / 'runtime-controls.db').as_posix()}"
    )
    try:
        database.create_schema()
        inspector = inspect(database.engine)
        tables = set(inspector.get_table_names())
        assert {
            "runtime_admission_buckets",
            "runtime_admission_reservations",
            "runtime_event_dedupes",
        } <= tables
        reservation_indexes = {
            item["name"]
            for item in inspector.get_indexes(
                "runtime_admission_reservations"
            )
        }
        assert "uq_runtime_admission_active_slot" in reservation_indexes
        with UnitOfWork(database) as uow:
            state = uow.task_runtime.admission_state(AGENT_PLAN_KIND)
        assert state["capacity"] == 10
        assert state["active_count"] == 0
    finally:
        database.engine.dispose()
