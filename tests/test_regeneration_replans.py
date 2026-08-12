from app.application.commands import (
    CancelRegenerationPlanCommand,
    CommandBus,
    CommandContext,
    CreateRegenerationPlanCommand,
    PersistGeneratedArtifactCommand,
    StartRegenerationPlanCommand,
)
from app.application.regeneration_plan_service import (
    advance_regeneration_plan,
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.store import UnitOfWork


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
                    "prompt_version": "replan-test@1",
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
                "prompt_version": "replan-test@1",
                "parameters": {},
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=source_job["id"],
            idempotency_key=f"job:{source_job['id']}:artifact:1",
        ),
    ).result


def _stale_plan(app, client, project):
    source = _artifact(client, project["id"], "重新规划输入")
    output = _generated_from(
        app,
        project["id"],
        "重新规划输出",
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
            idempotency_key=f"replan-source:{project['id']}:{snapshot}"
        ),
    ).result
    return source, output, plan


def _cancel(app, plan):
    return CommandBus(app.state.database).execute(
        CancelRegenerationPlanCommand(plan_id=plan["id"]),
        CommandContext(
            idempotency_key=f"replan-cancel:{plan['id']}"
        ),
    ).result


def test_replan_canceled_plan_reads_current_graph_and_records_lineage(
    app,
    client,
    project,
):
    source, output, plan = _stale_plan(app, client, project)
    canceled = _cancel(app, plan)
    assert canceled["status"] == "canceled"

    manual = client.post(
        f"/api/artifacts/{output['id']}/versions",
        json={"payload": {"body": "人工版本"}},
    )
    assert manual.status_code == 201, manual.text

    response = client.post(
        f"/api/artifact-regeneration/plans/{plan['id']}/replan",
        json={
            "expected_source_status": "canceled",
            "expected_execution_attempt": 0,
            "reason": "目标版本已由人工修改",
            "client_token": "current-graph",
        },
    )
    assert response.status_code == 201, response.text
    target = response.json()
    assert target["id"] != plan["id"]
    assert target["status"] == "draft"
    assert target["root_artifact_ids"] == [source["id"]]
    assert target["snapshot_sha256"] != plan["snapshot_sha256"]
    assert [step["artifact_id"] for step in target["steps"]] == [
        source["id"]
    ]
    with UnitOfWork(app.state.database) as uow:
        current_source = uow.artifacts.get(source["id"])
    assert target["steps"][0]["expected_version_id"] == (
        current_source["current_version_id"]
    )

    source_lineage = client.get(
        f"/api/artifact-regeneration/plans/{plan['id']}/lineage"
    )
    target_lineage = client.get(
        f"/api/artifact-regeneration/plans/{target['id']}/lineage"
    )
    assert source_lineage.status_code == 200
    assert target_lineage.status_code == 200
    relation = source_lineage.json()["replanned_by"]
    assert relation["source_plan_id"] == plan["id"]
    assert relation["target_plan_id"] == target["id"]
    assert relation["reason"] == "目标版本已由人工修改"
    assert target_lineage.json()["replanned_from"]["id"] == (
        relation["id"]
    )


def test_replan_waits_until_canceled_child_job_is_terminal(
    app,
    client,
    project,
):
    _source, _output, plan = _stale_plan(app, client, project)
    CommandBus(app.state.database).execute(
        StartRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        CommandContext(
            idempotency_key=f"replan-start:{plan['id']}"
        ),
    )
    engine = RecordingJobEngine()
    running = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        engine,
    )
    job_id = next(
        step["job_id"]
        for step in running["steps"]
        if step.get("job_id")
    )
    canceled = _cancel(app, running)
    assert canceled["status"] == "canceled"

    endpoint = (
        f"/api/artifact-regeneration/plans/{plan['id']}/replan"
    )
    body = {
        "expected_source_status": "canceled",
        "expected_execution_attempt": 0,
        "client_token": "before-job-terminal",
    }
    blocked = client.post(endpoint, json=body)
    assert blocked.status_code == 409, blocked.text

    with UnitOfWork(app.state.database) as uow:
        uow.jobs.update_state(job_id, "canceled")
    created = client.post(
        endpoint,
        json={**body, "client_token": "after-job-terminal"},
    )
    assert created.status_code == 201, created.text


def test_replan_client_token_replays_and_source_has_one_child(
    app,
    client,
    project,
):
    _source, _output, plan = _stale_plan(app, client, project)
    _cancel(app, plan)
    endpoint = (
        f"/api/artifact-regeneration/plans/{plan['id']}/replan"
    )
    body = {
        "expected_source_status": "canceled",
        "expected_execution_attempt": 0,
        "client_token": "same-intent",
    }
    first = client.post(endpoint, json=body)
    replay = client.post(endpoint, json=body)
    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]

    duplicate = client.post(
        endpoint,
        json={**body, "client_token": "different-intent"},
    )
    assert duplicate.status_code == 409, duplicate.text


def test_replan_rejects_stale_source_status_or_attempt(
    app,
    client,
    project,
):
    _source, _output, plan = _stale_plan(app, client, project)
    _cancel(app, plan)
    endpoint = (
        f"/api/artifact-regeneration/plans/{plan['id']}/replan"
    )
    wrong_status = client.post(
        endpoint,
        json={
            "expected_source_status": "failed",
            "expected_execution_attempt": 0,
            "client_token": "wrong-status",
        },
    )
    assert wrong_status.status_code == 409
    wrong_attempt = client.post(
        endpoint,
        json={
            "expected_source_status": "canceled",
            "expected_execution_attempt": 1,
            "client_token": "wrong-attempt",
        },
    )
    assert wrong_attempt.status_code == 409
