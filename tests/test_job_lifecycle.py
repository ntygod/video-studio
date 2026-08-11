import json
import time

import pytest
from sqlalchemy import text

from app.application.jobs.events import list_job_events_after
from app.application.jobs.lifecycle import reset_job_for_retry
from app.store import UnitOfWork
from app.store.repositories import ConflictError


def _create_job(app, project_id: str) -> str:
    with UnitOfWork(app.state.database) as uow:
        return uow.jobs.create(
            {
                "project_id": project_id,
                "job_type": "llm",
                "payload": {"capability": "llm", "prompt": "测试"},
            }
        )["id"]


def test_manual_retry_clears_all_runtime_state(app, project):
    job_id = _create_job(app, project["id"])
    with app.state.database.engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE jobs
                SET status = 'canceled',
                    progress = 0.75,
                    cancel_requested = 1,
                    attempt = 2,
                    lease_until = :lease_until,
                    worker_id = 'old-worker',
                    result_json = :result,
                    error = 'old error'
                WHERE id = :job_id
                """
            ),
            {
                "job_id": job_id,
                "lease_until": time.time() + 60,
                "result": json.dumps({"stale": True}),
            },
        )

    job = reset_job_for_retry(app.state.database, job_id)

    assert job["status"] == "queued"
    assert job["progress"] == 0.0
    assert job["cancel_requested"] is False
    assert job["attempt"] == 0
    assert job["lease_until"] is None
    assert job["worker_id"] == ""
    assert job["result"] is None
    assert job["error"] == ""
    assert job["events"][-1]["stage"] == "retry"


def test_manual_retry_rejects_non_terminal_job(app, project):
    job_id = _create_job(app, project["id"])

    with pytest.raises(ConflictError, match="失败或已取消"):
        reset_job_for_retry(app.state.database, job_id)


def test_job_event_cursor_returns_persisted_events(app, project):
    job_id = _create_job(app, project["id"])
    with UnitOfWork(app.state.database) as uow:
        first = uow.jobs.add_event(job_id, "第一条", stage="one")
        second = uow.jobs.add_event(job_id, "第二条", stage="two")

    events = list_job_events_after(
        app.state.database,
        project_id=project["id"],
    )
    assert [event["message"] for event in events] == ["第一条", "第二条"]

    cursor = (float(second["created_at"]), str(second["id"]))
    time.sleep(0.001)
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.add_event(job_id, "第三条", stage="three")

    later = list_job_events_after(
        app.state.database,
        project_id=project["id"],
        after_created_at=cursor[0],
        after_id=cursor[1],
    )
    assert [event["message"] for event in later] == ["第三条"]
    assert first["id"] != second["id"]
