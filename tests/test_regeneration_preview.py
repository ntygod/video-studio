from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
)
from app.store import UnitOfWork


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
        job = uow.jobs.create(
            {
                "project_id": project_id,
                "job_type": "generate",
                "payload": {
                    "capability": "llm",
                    "prompt": f"生成{name}",
                    "prompt_version": "preview-test@1",
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
            provenance={
                "prompt_version": "preview-test@1",
                "parameters": {},
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=job["id"],
            idempotency_key=f"job:{job['id']}:artifact:1",
        ),
    ).result


def _operations(client, project_id: str):
    with UnitOfWork(client.app.state.database) as uow:
        return uow.operations.list(project_id, limit=500)


def test_regeneration_preview_orders_downstream_and_is_read_only(
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

    before = len(_operations(client, project["id"]))
    response = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/preview",
        json={
            "artifact_ids": [source["id"]],
            "include_downstream": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    after = len(_operations(client, project["id"]))

    assert after == before
    assert body["order"] == [
        source["id"],
        middle["id"],
        output["id"],
    ]
    by_id = {step["artifact_id"]: step for step in body["steps"]}
    assert by_id[source["id"]]["execution_state"] == "skipped"
    assert by_id[middle["id"]]["action"] == "regenerate_llm"
    assert by_id[middle["id"]]["execution_state"] == "ready"
    assert by_id[output["id"]]["execution_state"] == (
        "waiting_for_predecessors"
    )
    assert by_id[output["id"]]["depends_on"] == [middle["id"]]
    assert body["summary"]["automatable"] == 2


def test_regeneration_preview_blocks_unselected_stale_upstream(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "根输入")
    middle = _generated_from(
        app,
        project["id"],
        "中间结果",
        source["current_version"]["id"],
    )
    output = _generated_from(
        app,
        project["id"],
        "末端结果",
        middle["current_version"]["id"],
    )
    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "根输入 v2"}},
    )

    response = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/preview",
        json={
            "artifact_ids": [output["id"]],
            "include_downstream": False,
        },
    )
    assert response.status_code == 200, response.text
    step = response.json()["steps"][0]
    assert step["execution_state"] == "blocked"
    assert any(
        blocker["code"] == "external_upstream_not_fresh"
        and blocker.get("entity_id") == middle["id"]
        for blocker in step["blockers"]
    )


def test_regeneration_preview_requires_timeline_asset_replacements(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "将缺失的素材",
            "uri": f"{project['id']}/missing.png",
            "mime_type": "image/png",
        },
    ).json()
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "preview-timeline"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]
    assert client.delete(
        f"/api/assets/{asset['id']}"
    ).status_code == 200

    response = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/preview",
        json={"artifact_ids": [timeline["id"]]},
    )
    assert response.status_code == 200, response.text
    step = response.json()["steps"][0]
    assert step["action"] == "repair_timeline_assets"
    assert step["execution_state"] == "requires_input"
    assert step["direct_missing_asset_ids"] == [asset["id"]]
    assert step["can_execute_automatically"] is False


def test_regeneration_preview_hides_foreign_artifact(
    client,
    project,
):
    other = client.post(
        "/api/projects",
        json={"title": "另一个项目"},
    ).json()
    foreign = _artifact(client, other["id"], "外部稿件")
    response = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/preview",
        json={"artifact_ids": [foreign["id"]]},
    )
    assert response.status_code == 404
