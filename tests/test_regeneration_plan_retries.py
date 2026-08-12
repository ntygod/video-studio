import pytest

from app.application.commands import (
    CommandBus,
    CommandContext,
    CreateRegenerationPlanCommand,
    PersistGeneratedArtifactCommand,
    RetryRegenerationPlanCommand,
    StartRegenerationPlanCommand,
)
from app.application.regeneration_plan_service import (
    advance_plan_for_job,
    advance_regeneration_plan,
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


def _artifact(client, project_id: str, name: str):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": "generated",
            "name": name,
            "payload": {"body": name},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _generated_from(
    app,
    project_id: str,
    name: str,
    input_version_id: str,
):
    with UnitOfWork(app.state.database) as uow:
        source_job = uow.jobs.create(
            {
                "project_id": project_id,
                "job_type": "generate",
                "payload": {
                    "capability": "llm",
                    "prompt": f"生成{name}",
                    "prompt_version": "retry-test@1",
                    "schema_id": "freeform",
                    "artifact_kind": "generated",
                    "artifact_name": name,
                    "input_version_ids": [input_version_id],
                    "context": {},
                    "parameters": {},
                },
            }
        )
    return CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project_id,
            payload={"body": name},
            kind="generated",
            name=name,
            input_version_ids=[input_version_id],
            dependency_metadata={"job_id": source_job["id"]},
            provenance={
                "prompt_version": "retry-test@1",
                "parameters": {},
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=source_job["id"],
            idempotency_key=f"job:{source_job['id']}:artifact:1",
        ),
    ).result


def _failed_plan(app, client, project):
    source = _artifact(client, project["id"], "重试输入")
    output = _generated_from(
        app,
        project["id"],
        "重试输出",
        source["current_version"]["id"],
    )
    advanced = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "输入 v2"}},
    )
    assert advanced.status_code == 201, advanced.text

    with UnitOfWork(app.state.database) as uow:
        preview = preview_regeneration_cascade(
            uow,
            project["id"],
            [source["id"]],
            include_downstream=True,
        )
    snapshot = regeneration_preview_snapshot_sha256(preview)
    plan = CommandBus(app.state.database).execute(
        CreateRegenerationPlanCommand(
            project_id=project["id"],
            artifact_ids=[source["id"]],
            include_downstream=True,
            expected_snapshot_sha256=snapshot,
        ),
        CommandContext(
            idempotency_key=f"retry-plan:{project['id']}:{snapshot}"
        ),
    ).result
    CommandBus(app.state.database).execute(
        StartRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        CommandContext(
            idempotency_key=f"retry-plan-start:{plan['id']}"
        ),
    )
    first_engine = RecordingJobEngine()
    running = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        first_engine,
    )
    step = next(
        item
        for item in running["steps"]
        if item["artifact_id"] == output["id"]
    )
    first_job_id = step["job_id"]
    assert first_job_id
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.update_state(
            first_job_id,
            "failed",
            error="provider outage",
        )
    failed = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        first_engine,
    )
    assert failed["status"] == "failed"
    failed_step = next(
        item for item in failed["steps"] if item["id"] == step["id"]
    )
    assert failed_step["status"] == "failed"
    return source, output, failed, failed_step, first_job_id


def test_failed_plan_retry_preserves_history_and_creates_new_job(
    app,
    client,
    project,
):
    _source, _output, plan, step, first_job_id = _failed_plan(
        app,
        client,
        project,
    )
    key = f"retry-attempt:{plan['id']}:0"
    execution = CommandBus(app.state.database).execute(
        RetryRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_execution_attempt=0,
        ),
        CommandContext(idempotency_key=key),
    )
    retried = execution.result

    assert retried["status"] == "running"
    assert retried["execution_attempt"] == 1
    reset = next(
        item for item in retried["steps"] if item["id"] == step["id"]
    )
    assert reset["status"] == "waiting_for_predecessors"
    assert reset["execution_attempt"] == 1
    assert reset["job_id"] is None
    assert len(reset["attempt_history"]) == 1
    history = reset["attempt_history"][0]
    assert history["attempt"] == 0
    assert history["job_id"] == first_job_id
    assert history["error"] == "provider outage"

    engine = RecordingJobEngine()
    running = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        engine,
    )
    current = next(
        item for item in running["steps"] if item["id"] == step["id"]
    )
    assert current["status"] == "queued"
    assert current["job_id"] != first_job_id
    assert engine.submitted == [current["job_id"]]

    with UnitOfWork(app.state.database) as uow:
        new_job = uow.jobs.get(current["job_id"])
        jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if (job.get("payload") or {}).get(
                "_regeneration_plan_id"
            )
            == plan["id"]
        ]
        retry_operation = uow.operations.find_by_idempotency_key(
            f"regeneration-plan:{plan['id']}:"
            f"step:{step['id']}:attempt:1"
        )
    assert new_job["payload"]["_regeneration_plan_step_attempt"] == 1
    assert len(jobs) == 2
    assert retry_operation is not None
    assert retry_operation["status"] == "succeeded"


def test_retry_command_replays_without_incrementing_attempt_twice(
    app,
    client,
    project,
):
    _source, _output, plan, _step, _job_id = _failed_plan(
        app,
        client,
        project,
    )
    command = RetryRegenerationPlanCommand(
        plan_id=plan["id"],
        expected_execution_attempt=0,
    )
    context = CommandContext(
        idempotency_key=f"retry-idempotent:{plan['id']}:0"
    )
    first = CommandBus(app.state.database).execute(command, context)
    replay = CommandBus(app.state.database).execute(
        RetryRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_execution_attempt=0,
        ),
        context,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.result["execution_attempt"] == 1
    failed_steps = [
        step
        for step in replay.result["steps"]
        if step["attempt_history"]
    ]
    assert len(failed_steps) == 1
    assert len(failed_steps[0]["attempt_history"]) == 1


def test_retry_rejects_manual_target_version_drift(
    app,
    client,
    project,
):
    _source, output, plan, _step, _job_id = _failed_plan(
        app,
        client,
        project,
    )
    manual = client.post(
        f"/api/artifacts/{output['id']}/versions",
        json={"payload": {"body": "人工修改"}},
    )
    assert manual.status_code == 201, manual.text

    with pytest.raises(ConflictError, match="planned target version changed"):
        CommandBus(app.state.database).execute(
            RetryRegenerationPlanCommand(
                plan_id=plan["id"],
                expected_execution_attempt=0,
            ),
            CommandContext(
                idempotency_key=f"retry-drift:{plan['id']}:0"
            ),
        )


def test_old_job_callback_cannot_overwrite_new_attempt(
    app,
    client,
    project,
):
    _source, _output, plan, step, first_job_id = _failed_plan(
        app,
        client,
        project,
    )
    CommandBus(app.state.database).execute(
        RetryRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_execution_attempt=0,
        ),
        CommandContext(
            idempotency_key=f"retry-late-job:{plan['id']}:0"
        ),
    )
    engine = RecordingJobEngine()
    running = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        engine,
    )
    current = next(
        item for item in running["steps"] if item["id"] == step["id"]
    )
    second_job_id = current["job_id"]
    assert second_job_id != first_job_id

    with UnitOfWork(app.state.database) as uow:
        uow.jobs.update_state(
            first_job_id,
            "succeeded",
            result={
                "artifact_id": step["artifact_id"],
                "version_id": "obsolete-version",
            },
        )
    advance_plan_for_job(app.state.database, first_job_id, engine)

    with UnitOfWork(app.state.database) as uow:
        stored = uow.regeneration_plans.get_step(step["id"])
    assert stored["status"] == "queued"
    assert stored["job_id"] == second_job_id
    assert stored["execution_attempt"] == 1


def test_retry_api_uses_expected_attempt_for_network_replay(
    app,
    client,
    project,
):
    _source, _output, plan, step, first_job_id = _failed_plan(
        app,
        client,
        project,
    )
    engine = RecordingJobEngine()
    app.state.job_engine = engine
    endpoint = (
        f"/api/artifact-regeneration/plans/{plan['id']}/retry"
    )
    body = {"expected_execution_attempt": 0}
    first = client.post(endpoint, json=body)
    replay = client.post(endpoint, json=body)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["execution_attempt"] == 1
    assert replay.json()["execution_attempt"] == 1
    current = next(
        item
        for item in replay.json()["steps"]
        if item["id"] == step["id"]
    )
    assert current["job_id"] != first_job_id
    assert engine.submitted == [current["job_id"]]
