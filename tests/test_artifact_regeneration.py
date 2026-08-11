import pytest

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
)
from app.application.regeneration_service import (
    prepare_artifact_regeneration,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError


def _artifact(client, project_id: str, name: str, body: str):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": "generated",
            "name": name,
            "payload": {"body": body},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _job_context(job_id: str, key: str) -> CommandContext:
    return CommandContext(
        actor_type="job",
        actor_id=job_id,
        idempotency_key=key,
    )


def _replayable_output(app, client, project):
    source = _artifact(
        client,
        project["id"],
        "输入稿",
        "source-v1",
    )
    source_v1 = source["current_version"]["id"]
    with UnitOfWork(app.state.database) as uow:
        source_job = uow.jobs.create(
            {
                "project_id": project["id"],
                "job_type": "generate",
                "payload": {
                    "capability": "llm",
                    "prompt": "根据输入生成结果",
                    "prompt_version": "test@1",
                    "schema_id": "freeform",
                    "artifact_kind": "generated",
                    "artifact_name": "派生稿",
                    "context": {"legacy": "source-v1"},
                    "parameters": {"temperature": 0.2},
                    "input_version_ids": [source_v1],
                },
            }
        )
    output = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "output-v1"},
            kind="generated",
            name="派生稿",
            input_version_ids=[source_v1],
            dependency_metadata={
                "job_id": source_job["id"]
            },
            provenance={
                "prompt_version": "test@1",
                "parameters": {"temperature": 0.2},
            },
        ),
        _job_context(
            source_job["id"],
            f"job:{source_job['id']}:artifact:1",
        ),
    ).result
    return source, source_job, output


def test_regeneration_refreshes_inputs_and_appends_same_artifact(
    app,
    client,
    project,
):
    source, _source_job, output = _replayable_output(
        app,
        client,
        project,
    )
    output_v1 = output["current_version"]["id"]

    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "source-v2"}},
    )
    assert updated.status_code == 201, updated.text
    source_v2 = updated.json()["id"]

    with UnitOfWork(app.state.database) as uow:
        specification = prepare_artifact_regeneration(
            uow,
            output["id"],
        )
    payload = specification["payload"]
    assert payload["target_artifact_id"] == output["id"]
    assert payload["expected_target_version_id"] == output_v1
    assert payload["input_version_ids"] == [source_v2]
    assert payload["context"]["current_inputs"][0][
        "payload"
    ] == {"body": "source-v2"}
    assert "重新生成约束" in payload["prompt"]

    regenerated_job_id = "job-regenerate-output"
    regenerated = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "output-v2"},
            unit_id=specification["unit_id"],
            kind=output["kind"],
            name=output["name"],
            schema_id=output["schema_id"],
            input_version_ids=payload["input_version_ids"],
            dependency_metadata={
                "job_id": regenerated_job_id
            },
            provenance={
                "prompt_version": payload["prompt_version"],
                "parameters": payload["parameters"],
            },
            target_artifact_id=output["id"],
            expected_target_version_id=output_v1,
        ),
        _job_context(
            regenerated_job_id,
            f"job:{regenerated_job_id}:artifact:1",
        ),
    ).result

    assert regenerated["id"] == output["id"]
    assert regenerated["current_version"]["id"] != output_v1
    assert regenerated["current_version"]["version"] == 2
    with UnitOfWork(app.state.database) as uow:
        assert uow.artifact_graph.get_freshness(
            output["id"]
        )["status"] == "fresh"
        derivation = uow.artifact_graph.derivation(
            regenerated["current_version"]["id"]
        )
    assert [
        edge["upstream_version_id"]
        for edge in derivation["dependencies"]
    ] == [source_v2]


def test_regeneration_endpoint_reuses_job_for_same_target_version(
    app,
    client,
    project,
):
    source, _source_job, output = _replayable_output(
        app,
        client,
        project,
    )
    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "source-v2"}},
    )
    assert updated.status_code == 201, updated.text

    first = client.post(
        f"/api/artifacts/{output['id']}/regenerate"
    )
    second = client.post(
        f"/api/artifacts/{output['id']}/regenerate"
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    with UnitOfWork(app.state.database) as uow:
        regeneration_jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if (
                job.get("payload") or {}
            ).get("target_artifact_id") == output["id"]
        ]
        operations = uow.operations.list(
            project["id"],
            limit=500,
        )
    assert [job["id"] for job in regeneration_jobs] == [
        first.json()["id"]
    ]
    matching = [
        operation
        for operation in operations
        if operation.get("idempotency_key")
        == (
            "artifact-regenerate:"
            f"{output['id']}:"
            f"{output['current_version']['id']}"
        )
    ]
    assert len(matching) == 1


def test_regeneration_rejects_target_changed_while_job_runs(
    app,
    client,
    project,
):
    target = _artifact(
        client,
        project["id"],
        "目标稿",
        "v1",
    )
    expected = target["current_version"]["id"]
    changed = client.post(
        f"/api/artifacts/{target['id']}/versions",
        json={"payload": {"body": "manual-v2"}},
    )
    assert changed.status_code == 201

    with pytest.raises(
        ConflictError,
        match="target Artifact changed",
    ):
        CommandBus(app.state.database).execute(
            PersistGeneratedArtifactCommand(
                project_id=project["id"],
                payload={"body": "late-generated"},
                kind=target["kind"],
                name=target["name"],
                schema_id=target["schema_id"],
                target_artifact_id=target["id"],
                expected_target_version_id=expected,
            ),
            _job_context(
                "job-late",
                "job:job-late:artifact:1",
            ),
        )


def test_regeneration_requires_replayable_job_provenance(
    client,
    project,
):
    source = _artifact(
        client,
        project["id"],
        "手工输入",
        "source-v1",
    )
    output = _artifact(
        client,
        project["id"],
        "手工派生",
        "output-v1",
    )
    derived = client.post(
        "/api/artifact-versions/"
        f"{output['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                source["current_version"]["id"]
            ]
        },
        headers={"Idempotency-Key": "manual-derivation"},
    )
    assert derived.status_code == 201, derived.text
    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "source-v2"}},
    )

    response = client.post(
        f"/api/artifacts/{output['id']}/regenerate"
    )
    assert response.status_code == 422
    assert "可重放" in response.json()["detail"]
