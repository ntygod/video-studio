import pytest

from app.application.commands import (
    CancelRegenerationPlanCommand,
    CommandBus,
    CommandContext,
    CreateRegenerationPlanCommand,
    PersistGeneratedArtifactCommand,
    SetRegenerationPlanStepInputCommand,
    StartRegenerationPlanCommand,
)
from app.application.regeneration_plan_service import (
    advance_plan_for_job,
    advance_regeneration_plan,
    recover_regeneration_plans,
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
        self.canceled: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def cancel(self, job_id: str) -> None:
        self.canceled.append(job_id)


def _artifact(client, project_id: str, name: str, body: str = ""):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": "generated",
            "name": name,
            "payload": {"body": body or name},
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
                    "prompt_version": "plan-test@1",
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
                "prompt_version": "plan-test@1",
                "parameters": {},
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=source_job["id"],
            idempotency_key=f"job:{source_job['id']}:artifact:1",
        ),
    ).result


def _create_plan(
    app,
    project_id: str,
    artifact_ids: list[str],
    *,
    include_downstream: bool = True,
):
    with UnitOfWork(app.state.database) as uow:
        preview = preview_regeneration_cascade(
            uow,
            project_id,
            artifact_ids,
            include_downstream=include_downstream,
        )
    snapshot = regeneration_preview_snapshot_sha256(preview)
    return CommandBus(app.state.database).execute(
        CreateRegenerationPlanCommand(
            project_id=project_id,
            artifact_ids=artifact_ids,
            include_downstream=include_downstream,
            expected_snapshot_sha256=snapshot,
        ),
        CommandContext(
            idempotency_key=(
                f"test-plan:{project_id}:{snapshot}"
            )
        ),
    ).result


def _start_plan(app, plan: dict, engine: RecordingJobEngine):
    CommandBus(app.state.database).execute(
        StartRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        CommandContext(
            idempotency_key=f"test-plan-start:{plan['id']}"
        ),
    )
    return advance_regeneration_plan(
        app.state.database,
        plan["id"],
        engine,
    )


def _complete_llm_step_job(app, job_id: str, body: str):
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.get(job_id)
        payload = job["payload"]
        target = uow.artifacts.get(payload["target_artifact_id"])
    execution = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=job["project_id"],
            unit_id=job["unit_id"],
            payload={"body": body},
            kind=target["kind"],
            name=target["name"],
            schema_id=target["schema_id"],
            input_version_ids=payload["input_version_ids"],
            input_asset_ids=payload.get("input_asset_ids") or [],
            dependency_metadata={"job_id": job_id},
            provenance={
                "prompt_version": payload.get("prompt_version") or "",
                "parameters": payload.get("parameters") or {},
            },
            target_artifact_id=target["id"],
            expected_target_version_id=(
                payload["expected_target_version_id"]
            ),
        ),
        CommandContext(
            actor_type="job",
            actor_id=job_id,
            idempotency_key=f"job:{job_id}:artifact:1",
        ),
    )
    artifact = execution.result
    version = artifact["current_version"]
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.update_state(
            job_id,
            "succeeded",
            progress=1.0,
            result={
                "artifact_id": artifact["id"],
                "version_id": version["id"],
                "payload": version["payload"],
            },
        )
    return artifact


def _step_by_artifact(plan: dict, artifact_id: str):
    return next(
        step
        for step in plan["steps"]
        if step["artifact_id"] == artifact_id
    )


def test_plan_releases_llm_jobs_in_dependency_order_and_recovers(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "输入")
    middle = _generated_from(
        app,
        project["id"],
        "中间稿",
        source["current_version"]["id"],
    )
    output = _generated_from(
        app,
        project["id"],
        "最终稿",
        middle["current_version"]["id"],
    )
    advanced = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "输入 v2"}},
    )
    assert advanced.status_code == 201, advanced.text

    plan = _create_plan(app, project["id"], [source["id"]])
    engine = RecordingJobEngine()
    running = _start_plan(app, plan, engine)

    assert running["status"] == "running"
    assert len(engine.submitted) == 1
    middle_step = _step_by_artifact(running, middle["id"])
    output_step = _step_by_artifact(running, output["id"])
    assert middle_step["status"] == "queued"
    assert output_step["status"] == "waiting_for_predecessors"
    assert output_step["job_id"] is None

    first_job_id = middle_step["job_id"]
    with UnitOfWork(app.state.database) as uow:
        first_job = uow.jobs.get(first_job_id)
    assert first_job["payload"]["_regeneration_plan_id"] == plan["id"]
    assert first_job["payload"]["_regeneration_plan_step_id"] == (
        middle_step["id"]
    )

    regenerated_middle = _complete_llm_step_job(
        app,
        first_job_id,
        "中间稿 v2",
    )
    # Simulate a process restart after the Job transaction committed but
    # before the original worker notified the plan coordinator.
    assert recover_regeneration_plans(app.state.database, engine) == 1

    with UnitOfWork(app.state.database) as uow:
        after_recovery = uow.regeneration_plans.get(plan["id"])
    middle_step = _step_by_artifact(after_recovery, middle["id"])
    output_step = _step_by_artifact(after_recovery, output["id"])
    assert middle_step["status"] == "succeeded"
    assert middle_step["result"]["version_id"] == (
        regenerated_middle["current_version"]["id"]
    )
    assert output_step["status"] == "queued"
    assert len(engine.submitted) == 2

    second_job_id = output_step["job_id"]
    regenerated_output = _complete_llm_step_job(
        app,
        second_job_id,
        "最终稿 v2",
    )
    advance_plan_for_job(app.state.database, second_job_id, engine)

    with UnitOfWork(app.state.database) as uow:
        completed = uow.regeneration_plans.get(plan["id"])
        matching_jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if (job.get("payload") or {}).get(
                "_regeneration_plan_id"
            )
            == plan["id"]
        ]
    assert completed["status"] == "succeeded"
    assert completed["summary"]["completed"] == 3
    assert len(matching_jobs) == 2
    assert regenerated_output["current_version"]["version"] == 2

    # Replaying the same start Operation never creates another Job.
    replay = CommandBus(app.state.database).execute(
        StartRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        CommandContext(
            idempotency_key=f"test-plan-start:{plan['id']}"
        ),
    )
    assert replay.replayed is True
    assert replay.result["status"] == "succeeded"


def test_plan_recompiles_stale_timeline_synchronously(
    app,
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "镜头",
            "uri": f"{project['id']}/shot.png",
            "mime_type": "image/png",
        },
    ).json()
    edit_plan = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "edit_plan",
            "name": "剪辑方案",
            "payload": {
                "decisions": [
                    {
                        "asset_id": asset["id"],
                        "duration": 2,
                    }
                ]
            },
        },
    ).json()
    client.post(
        "/api/artifact-versions/"
        f"{edit_plan['current_version']['id']}/approve"
    )
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "plan-timeline-v1"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]

    advanced = client.post(
        f"/api/artifacts/{edit_plan['id']}/versions",
        json={
            "payload": {
                "decisions": [
                    {
                        "asset_id": asset["id"],
                        "duration": 3,
                    }
                ]
            }
        },
    )
    assert advanced.status_code == 201, advanced.text

    plan = _create_plan(app, project["id"], [edit_plan["id"]])
    engine = RecordingJobEngine()
    completed = _start_plan(app, plan, engine)

    assert engine.submitted == []
    assert completed["status"] == "succeeded"
    timeline_step = _step_by_artifact(completed, timeline["id"])
    assert timeline_step["action"] == "recompile_timeline"
    assert timeline_step["status"] == "succeeded"
    with UnitOfWork(app.state.database) as uow:
        current = uow.artifacts.get(timeline["id"])
        freshness = uow.artifact_graph.get_freshness(timeline["id"])
    assert current["current_version"]["version"] == 2
    assert freshness["status"] == "fresh"


def test_started_plan_resumes_after_timeline_replacement_input(
    app,
    client,
    project,
):
    missing = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "旧素材",
            "uri": f"{project['id']}/old.png",
            "mime_type": "image/png",
        },
    ).json()
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "plan-repair-timeline"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]
    assert client.delete(
        f"/api/assets/{missing['id']}"
    ).status_code == 200

    plan = _create_plan(app, project["id"], [timeline["id"]])
    engine = RecordingJobEngine()
    blocked = _start_plan(app, plan, engine)
    assert blocked["status"] == "blocked"
    step = _step_by_artifact(blocked, timeline["id"])
    assert step["status"] == "requires_input"

    replacement = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "替代素材",
            "uri": f"{project['id']}/replacement.png",
            "mime_type": "image/png",
        },
    ).json()
    CommandBus(app.state.database).execute(
        SetRegenerationPlanStepInputCommand(
            step_id=step["id"],
            replacements={missing["id"]: replacement["id"]},
        ),
        CommandContext(
            idempotency_key=f"test-plan-input:{step['id']}"
        ),
    )
    completed = advance_regeneration_plan(
        app.state.database,
        plan["id"],
        engine,
    )

    assert completed["status"] == "succeeded"
    repaired = _step_by_artifact(completed, timeline["id"])
    assert repaired["status"] == "succeeded"
    assert repaired["input"]["replacements"] == {
        missing["id"]: replacement["id"]
    }
    with UnitOfWork(app.state.database) as uow:
        current = uow.artifacts.get(timeline["id"])
        freshness = uow.artifact_graph.get_freshness(timeline["id"])
    assert current["current_version"]["version"] == 2
    assert freshness["status"] == "fresh"


def test_plan_cancel_requests_running_child_job_cancel(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "输入")
    downstream = _generated_from(
        app,
        project["id"],
        "输出",
        source["current_version"]["id"],
    )
    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "输入 v2"}},
    )
    plan = _create_plan(app, project["id"], [source["id"]])
    engine = RecordingJobEngine()
    running = _start_plan(app, plan, engine)
    step = _step_by_artifact(running, downstream["id"])

    canceled = CommandBus(app.state.database).execute(
        CancelRegenerationPlanCommand(plan_id=plan["id"]),
        CommandContext(
            idempotency_key=f"test-plan-cancel:{plan['id']}"
        ),
    ).result
    assert canceled["status"] == "canceled"
    assert _step_by_artifact(canceled, downstream["id"])["status"] == (
        "canceled"
    )
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.get(step["job_id"])
    assert job["cancel_requested"] is True


def test_plan_start_rejects_target_version_drift(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "输入")
    downstream = _generated_from(
        app,
        project["id"],
        "输出",
        source["current_version"]["id"],
    )
    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "输入 v2"}},
    )
    plan = _create_plan(app, project["id"], [source["id"]])
    manual = client.post(
        f"/api/artifacts/{downstream['id']}/versions",
        json={"payload": {"body": "人工改写"}},
    )
    assert manual.status_code == 201, manual.text

    with pytest.raises(ConflictError, match="planned target version changed"):
        CommandBus(app.state.database).execute(
            StartRegenerationPlanCommand(
                plan_id=plan["id"],
                expected_snapshot_sha256=plan["snapshot_sha256"],
            ),
            CommandContext(
                idempotency_key=f"drift-plan-start:{plan['id']}"
            ),
        )
    with UnitOfWork(app.state.database) as uow:
        stored = uow.regeneration_plans.get(plan["id"])
    assert stored["status"] == "draft"


def test_plan_create_api_is_idempotent_and_listable(
    app,
    client,
    project,
):
    artifact = _artifact(client, project["id"], "普通稿件")
    body = {
        "artifact_ids": [artifact["id"]],
        "include_downstream": True,
    }
    first = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/plans",
        json=body,
    )
    second = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/plans",
        json=body,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    fetched = client.get(
        f"/api/artifact-regeneration/plans/{first.json()['id']}"
    )
    listed = client.get(
        f"/api/projects/{project['id']}/artifact-regeneration/plans"
    )
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert fetched.json()["snapshot_sha256"]
    assert [item["id"] for item in listed.json()] == [first.json()["id"]]
