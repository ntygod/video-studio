from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
)
from app.application.regeneration_service import (
    prepare_artifact_regeneration,
)
from app.store import UnitOfWork


def _context(job_id: str, key: str) -> CommandContext:
    return CommandContext(
        actor_type="job",
        actor_id=job_id,
        idempotency_key=key,
    )


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


def test_generated_artifact_persists_first_class_asset_inputs(
    app,
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "reference",
            "name": "参考图",
            "uri": f"{project['id']}/reference.png",
            "mime_type": "image/png",
            "metadata": {"purpose": "character"},
        },
    ).json()
    result = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "generated"},
            kind="generated",
            name="带参考图的生成稿",
            input_asset_ids=[asset["id"]],
            provenance={"prompt_version": "asset-test@1"},
        ),
        _context(
            "job-with-asset",
            "job:job-with-asset:artifact:1",
        ),
    ).result

    dependencies = client.get(
        f"/api/artifacts/{result['id']}/asset-dependencies"
    ).json()
    assert [item["upstream_asset_id"] for item in dependencies] == [
        asset["id"]
    ]
    assert dependencies[0]["dependency_type"] == "uses_asset"

    deleted = client.delete(f"/api/assets/{asset['id']}")
    assert deleted.status_code == 200, deleted.text
    freshness = client.get(
        f"/api/artifacts/{result['id']}/freshness"
    ).json()
    assert freshness["status"] == "blocked"
    assert freshness["blocked_by_asset_ids"] == [asset["id"]]


def test_generate_endpoint_keeps_asset_inputs_in_job_payload(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "reference",
            "name": "上下文图",
            "uri": f"{project['id']}/context.png",
        },
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={
            "capability": "llm",
            "prompt": "读取参考素材",
            "input_asset_ids": [asset["id"]],
        },
        headers={"Idempotency-Key": "generate-with-asset"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["payload"]["input_asset_ids"] == [
        asset["id"]
    ]


def test_regeneration_preserves_current_asset_inputs(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "上游文本")
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "reference",
            "name": "角色参考图",
            "uri": f"{project['id']}/character.png",
            "mime_type": "image/png",
            "metadata": {"role": "lead"},
        },
    ).json()
    source_version_id = source["current_version"]["id"]
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.create(
            {
                "project_id": project["id"],
                "job_type": "generate",
                "payload": {
                    "capability": "llm",
                    "prompt": "根据文字和角色参考图生成",
                    "prompt_version": "mixed@1",
                    "input_version_ids": [source_version_id],
                    "input_asset_ids": [asset["id"]],
                    "context": {},
                },
            }
        )
    output = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            payload={"body": "output-v1"},
            kind="generated",
            name="混合输入产物",
            input_version_ids=[source_version_id],
            input_asset_ids=[asset["id"]],
            provenance={"prompt_version": "mixed@1"},
        ),
        _context(
            job["id"],
            f"job:{job['id']}:artifact:1",
        ),
    ).result

    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "source-v2"}},
    )
    assert updated.status_code == 201, updated.text
    with UnitOfWork(app.state.database) as uow:
        specification = prepare_artifact_regeneration(
            uow,
            output["id"],
        )
    payload = specification["payload"]
    assert payload["input_asset_ids"] == [asset["id"]]
    assert payload["context"]["current_asset_inputs"] == [
        {
            "asset_id": asset["id"],
            "asset_name": "角色参考图",
            "asset_kind": "reference",
            "mime_type": "image/png",
            "uri": f"{project['id']}/character.png",
            "metadata": {"role": "lead"},
        }
    ]
