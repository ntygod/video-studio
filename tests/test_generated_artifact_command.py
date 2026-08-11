from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
    generated_artifact_attempt,
)
from app.store import UnitOfWork


def _context(job_id: str, key: str) -> CommandContext:
    return CommandContext(
        actor_type="job",
        actor_id=job_id,
        idempotency_key=key,
    )


def test_generated_artifact_create_is_job_idempotent(
    app,
    project,
):
    job_id = "job-artifact-create"
    command = PersistGeneratedArtifactCommand(
        project_id=project["id"],
        payload={"body": "first result"},
        kind="generated",
        name="生成稿",
    )
    first = CommandBus(app.state.database).execute(
        command,
        _context(job_id, f"job:{job_id}:artifact:1"),
    )
    second = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "first result"},
            kind="generated",
            name="生成稿",
        ),
        _context(job_id, f"job:{job_id}:artifact:1"),
    )
    assert second.replayed is True
    assert second.result == first.result

    with UnitOfWork(app.state.database) as uow:
        generated = [
            artifact
            for artifact in uow.artifacts.list(project["id"])
            if artifact["kind"] == "generated"
        ]
    assert len(generated) == 1
    assert len(
        first.result.get("current_version", {})
    ) > 0


def test_job_recovery_replays_succeeded_artifact_before_model_call(
    app,
    project,
):
    job_id = "job-artifact-recovery"
    key = f"job:{job_id}:artifact:1"
    created = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "already persisted"},
            kind="generated",
            name="恢复稿",
        ),
        _context(job_id, key),
    ).result

    recovered, recovered_key = generated_artifact_attempt(
        app.state.database,
        job_id,
    )
    assert recovered_key == key
    assert recovered["id"] == created["id"]
    assert (
        recovered["current_version"]["id"]
        == created["current_version"]["id"]
    )


def test_singleton_generation_appends_and_replays_exact_version(
    app,
    client,
    project,
):
    original = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "edit_plan",
            "name": "制作方案",
            "schema_id": "open/edit_plan@1",
            "payload": {"version": "initial"},
        },
    ).json()
    job_id = "job-edit-plan"
    key = f"job:{job_id}:artifact:1"
    generated = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"version": "generated"},
            kind="edit_plan",
            name="制作方案",
            schema_id="open/edit_plan@1",
        ),
        _context(job_id, key),
    ).result
    assert generated["id"] == original["id"]
    generated_version_id = generated["current_version"]["id"]

    client.post(
        f"/api/artifacts/{original['id']}/versions",
        json={"payload": {"version": "later"}},
    )
    recovered, _ = generated_artifact_attempt(
        app.state.database,
        job_id,
    )
    assert recovered["id"] == original["id"]
    assert recovered["current_version"]["id"] == generated_version_id
    assert recovered["current_version"]["payload"] == {
        "version": "generated"
    }


def test_failed_persistence_gets_a_new_attempt_key(
    app,
    project,
):
    job_id = "job-artifact-failure"
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "artifact.generated.persist",
                "actor_type": "job",
                "actor_id": job_id,
                "target_type": "project",
                "target_id": project["id"],
                "idempotency_key": f"job:{job_id}:artifact:1",
                "arguments": {},
                "preconditions": [],
            }
        )
        uow.operations.fail(operation["id"], "invalid output")

    recovered, key = generated_artifact_attempt(
        app.state.database,
        job_id,
    )
    assert recovered is None
    assert key == f"job:{job_id}:artifact:2"
