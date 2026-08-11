from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
)
from app.store import UnitOfWork


def _artifact(client, project_id: str, kind: str, name: str, payload):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": kind,
            "name": name,
            "payload": payload,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_generated_artifact_records_provenance_in_same_operation(
    app,
    client,
    project,
):
    source = _artifact(
        client,
        project["id"],
        "script",
        "输入剧本",
        {"body": "source"},
    )
    operation = CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project["id"],
            kind="generated",
            name="生成结果",
            payload={"body": "output"},
            input_version_ids=[
                source["current_version"]["id"]
            ],
            provenance={
                "provider_profile_id": "provider-a",
                "model_id": "model-a",
                "prompt_version": "prompt-v2",
                "parameters": {"temperature": 0.1},
                "task_attempt_id": "attempt-1",
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id="job-provenance",
            idempotency_key="persist-with-provenance",
        ),
    )
    output = operation.result
    provenance = client.get(
        "/api/artifact-versions/"
        f"{output['current_version']['id']}/provenance"
    ).json()["provenance"]
    assert provenance["input_version_ids"] == [
        source["current_version"]["id"]
    ]
    assert provenance["provider_profile_id"] == "provider-a"
    assert provenance["model_id"] == "model-a"
    assert provenance["prompt_version"] == "prompt-v2"
    assert provenance["operation_id"] == operation.operation["id"]

    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "source-v2"}},
    )
    assert client.get(
        f"/api/artifacts/{output['id']}/freshness"
    ).json()["status"] == "stale"


def test_timeline_compile_records_selected_plan_and_assets(
    app,
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "video",
            "name": "镜头",
            "uri": f"{project['id']}/shot.mp4",
            "mime_type": "video/mp4",
            "metadata": {"duration": 2.0},
        },
    ).json()
    plan = _artifact(
        client,
        project["id"],
        "edit_plan",
        "制作方案",
        {
            "decisions": [
                {
                    "asset_id": asset["id"],
                    "duration": 2,
                    "reason": "approved plan",
                }
            ]
        },
    )
    client.post(
        "/api/artifact-versions/"
        f"{plan['current_version']['id']}/approve"
    )

    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
        headers={"Idempotency-Key": "compile-with-provenance"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]
    version_id = timeline["current_version"]["id"]
    derivation = client.get(
        f"/api/artifact-versions/{version_id}/provenance"
    ).json()["provenance"]
    assert derivation["input_version_ids"] == [
        plan["current_version"]["id"]
    ]
    assert derivation["prompt_version"] == "timeline-compiler@1"
    assert derivation["parameters"]["asset_ids"] == [asset["id"]]

    dependencies = client.get(
        f"/api/artifacts/{timeline['id']}/dependencies"
    ).json()
    edge = next(
        item
        for item in dependencies
        if item["downstream_artifact_id"] == timeline["id"]
    )
    assert edge["metadata"]["asset_ids"] == [asset["id"]]

    client.post(
        f"/api/artifacts/{plan['id']}/versions",
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
    assert client.get(
        f"/api/artifacts/{timeline['id']}/freshness"
    ).json()["status"] == "stale"


def test_timeline_without_artifact_input_still_records_asset_provenance(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "无计划素材",
            "uri": f"{project['id']}/image.png",
            "mime_type": "image/png",
        },
    ).json()
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
        headers={"Idempotency-Key": "compile-assets-only"},
    )
    assert compiled.status_code == 200, compiled.text
    version_id = compiled.json()["artifact"][
        "current_version"
    ]["id"]
    provenance = client.get(
        f"/api/artifact-versions/{version_id}/provenance"
    ).json()["provenance"]
    assert provenance["input_version_ids"] == []
    assert provenance["parameters"]["asset_ids"] == [asset["id"]]
