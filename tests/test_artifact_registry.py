from pydantic import BaseModel, ConfigDict, Field

from app.domain.artifact_registry import (
    ArtifactDefinition,
    ArtifactDefinitionRegistry,
)


def test_definition_endpoint_exposes_versioned_core_types(client):
    definitions = client.get(
        "/api/artifact-definitions",
        params={"include_schema": "false"},
    )
    assert definitions.status_code == 200
    by_kind = {item["kind"]: item for item in definitions.json()}
    assert {
        "brief",
        "project_bible",
        "story_outline",
        "screenplay",
        "shot_plan",
        "timeline",
    } <= set(by_kind)
    assert by_kind["story_outline"]["aliases"] == ["story_graph"]
    assert by_kind["timeline"]["schema_id"] == "video-studio/timeline@1"


def test_known_payload_is_normalized_and_schema_is_canonical(
    client,
    project,
):
    response = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "brief",
            "name": "另一个简报",
            "payload": {
                "title": "测试项目",
                "platforms": "douyin",
                "constraints": "禁止血腥",
            },
        },
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert artifact["schema_id"] == "video-studio/brief@1"
    version = artifact["current_version"]
    assert version["schema_version"] == 1
    assert version["payload"]["platforms"] == [
        {
            "platform": "douyin",
            "aspect_ratio": "",
            "target_seconds": None,
            "language": "zh-CN",
        }
    ]
    assert version["payload"]["constraints"][0]["kind"] == "custom"


def test_invalid_known_payload_is_422_and_does_not_append_version(
    client,
    project,
):
    artifacts = client.get(
        f"/api/projects/{project['id']}/artifacts",
        params={"include_payload": "true"},
    ).json()["items"]
    brief = next(item for item in artifacts if item["kind"] == "brief")
    before = client.get(
        f"/api/artifacts/{brief['id']}/versions"
    ).json()

    response = client.post(
        f"/api/artifacts/{brief['id']}/versions",
        json={
            "payload": {
                "title": "坏数据",
                "platforms": [
                    {
                        "platform": "demo",
                        "target_seconds": 0,
                    }
                ],
            }
        },
    )
    assert response.status_code == 422
    detail = response.json()
    assert detail["artifact_kind"] == "brief"
    assert detail["schema_id"] == "video-studio/brief@1"
    assert detail["errors"]

    after = client.get(
        f"/api/artifacts/{brief['id']}/versions"
    ).json()
    assert [item["id"] for item in after] == [
        item["id"] for item in before
    ]


def test_schema_id_mismatch_is_rejected(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "timeline",
            "name": "错误时间线",
            "schema_id": "video-studio/brief@1",
            "payload": {},
        },
    )
    assert response.status_code == 422
    assert "不接受 schema_id" in response.json()["detail"]


def test_unknown_artifact_kind_remains_open(client, project):
    payload = {"whatever": [1, {"nested": True}]}
    response = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "experimental_board",
            "name": "开放实验",
            "schema_id": "vendor/experimental@7",
            "schema_version": 7,
            "payload": payload,
        },
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert artifact["schema_id"] == "vendor/experimental@7"
    assert artifact["current_version"]["schema_version"] == 7
    assert artifact["current_version"]["payload"] == payload


class V2Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    tags: list[str] = Field(default_factory=list)


def test_registry_runs_explicit_schema_migrations():
    registry = ArtifactDefinitionRegistry()
    registry.register(
        ArtifactDefinition(
            kind="document",
            title="文档",
            schema_id="test/document@2",
            schema_version=2,
            model=V2Document,
            legacy_schema_ids=("test/document@1",),
            migrations={
                1: lambda payload: {
                    "title": payload["title"],
                    "tags": [payload["tag"]]
                    if payload.get("tag")
                    else [],
                }
            },
        )
    )

    result = registry.validate(
        "document",
        {"title": "A", "tag": "legacy"},
        schema_id="test/document@1",
        schema_version=1,
    )
    assert result.schema_id == "test/document@2"
    assert result.schema_version == 2
    assert result.payload == {"title": "A", "tags": ["legacy"]}
