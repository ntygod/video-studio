from app.application.commands import CommandBus, CommandContext, CreateJobCommand
from app.application.jobs import queue as job_queue
from app.application.jobs.lifecycle import reset_job_for_retry
from app.application.jobs.runtime_contract import MEDIA_JOB_PLAN_KIND, MEDIA_JOB_TASK_TYPE
from app.application.task_runtime import TaskRuntime
from app.store import UnitOfWork


def _create_image_job(app, project_id: str, key: str):
    return CommandBus(app.state.database).execute(
        CreateJobCommand(
            project_id=project_id,
            job_type="media",
            payload={
                "capability": "image",
                "prompt": "雨夜街头",
                "parameters": {},
            },
        ),
        CommandContext(idempotency_key=key),
    ).result


def test_runtime_media_job_is_invisible_to_legacy_queue(app, project):
    job = _create_image_job(app, project["id"], "runtime-media-owner")
    assert job["runtime_plan_id"]
    assert job["runtime_task_id"]
    assert job["runtime_generation"] == 1
    with UnitOfWork(app.state.database) as uow:
        plan = uow.task_runtime.get_plan(job["runtime_plan_id"])
        task = uow.task_runtime.get_task(job["runtime_task_id"])
    assert plan["kind"] == MEDIA_JOB_PLAN_KIND
    assert plan["status"] == "queued"
    assert task["task_type"] == MEDIA_JOB_TASK_TYPE
    assert task["status"] == "queued"
    assert job_queue.claim(app.state.database, "legacy-worker") is None

    with UnitOfWork(app.state.database) as uow:
        legacy = uow.jobs.create(
            {
                "project_id": project["id"],
                "job_type": "llm",
                "payload": {"capability": "llm"},
            }
        )
    claimed = job_queue.claim(app.state.database, "legacy-worker")
    assert claimed is not None
    assert claimed["id"] == legacy["id"]


def test_manual_retry_creates_new_runtime_generation(app, project):
    first = _create_image_job(app, project["id"], "runtime-media-retry")
    runtime = TaskRuntime(app.state.database)
    runtime.cancel(first["runtime_plan_id"], reason="test failure")
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.update_state(first["id"], "failed", error="provider failed")

    retried = reset_job_for_retry(app.state.database, first["id"])
    assert retried["runtime_generation"] == 2
    assert retried["runtime_plan_id"] != first["runtime_plan_id"]
    assert retried["runtime_task_id"] != first["runtime_task_id"]
    assert retried["status"] == "queued"
    with UnitOfWork(app.state.database) as uow:
        old_plan = uow.task_runtime.get_plan(first["runtime_plan_id"])
        new_plan = uow.task_runtime.get_plan(retried["runtime_plan_id"])
    assert old_plan["status"] == "canceled"
    assert new_plan["status"] == "queued"
    assert new_plan["input"]["runtime_generation"] == 2


def test_generic_job_api_creates_runtime_links(client, project):
    response = client.post(
        "/api/jobs",
        json={
            "project_id": project["id"],
            "job_type": "media",
            "payload": {
                "capability": "image",
                "prompt": "一张概念图",
                "parameters": {},
            },
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["runtime_plan_id"]
    assert body["runtime_task_id"]
