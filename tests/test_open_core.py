import httpx
import respx
from fastapi.testclient import TestClient

from app.application.providers import provider_for_capability
from app.integrations.llm import _pick_llm_model
from app.integrations.media.client import _model
from app.store import UnitOfWork


def test_project_and_units_are_unbounded_and_hierarchical(client, project):
    units = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "卷一", "unit_type": "volume"},
                {"title": "第二章", "unit_type": "chapter"},
                {"title": "第四季", "unit_type": "season"},
                {"title": "广告变体 B", "unit_type": "variant"},
                {"title": "深度嵌套", "unit_type": "whatever"},
            ]
        },
    )
    assert units.status_code == 201
    assert len(units.json()) == 5
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["unit_count"] == 5
    page = client.get(f"/api/projects/{project['id']}/units").json()
    assert len(page["items"]) == 5
    assert {unit["unit_type"] for unit in page["items"]} == {"volume", "chapter", "season", "variant", "whatever"}
    assert not detail["brief"]["platforms"]
    assert not detail["settings"]["delivery_profiles"]


def test_artifact_versions_are_append_only(client, project):
    artifacts = client.get(
        f"/api/projects/{project['id']}/artifacts", params={"include_payload": "true"}
    ).json()["items"]
    assert {artifact["kind"] for artifact in artifacts} == {"brief", "project_bible"}
    artifact = next(item for item in artifacts if item["kind"] == "brief")
    version_1 = artifact["current_version"]
    new_version = client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        json={"payload": {**version_1["payload"], "concept": "第二版"}, "note": "test"},
    )
    assert new_version.status_code == 201
    assert new_version.json()["version"] == 2
    versions = client.get(f"/api/artifacts/{artifact['id']}/versions").json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert versions[0]["parent_version_id"] == version_1["id"]


def test_saving_project_brief_updates_brief_artifact(client, project):
    detail = client.get(f"/api/projects/{project['id']}").json()
    artifacts_page = client.get(f"/api/projects/{project['id']}/artifacts").json()["items"]
    brief_artifact = next(item for item in artifacts_page if item["kind"] == "brief")
    response = client.patch(
        f"/api/projects/{project['id']}",
        json={
            "expected_revision": detail["revision"],
            "patch": {
                "brief": {
                    **detail["brief"],
                    "concept": "一段需要持续展开的悬疑故事",
                    "objective": "先完成第一章的结构",
                }
            },
        },
    )
    assert response.status_code == 200
    updated_artifact = client.get(f"/api/artifacts/{brief_artifact['id']}").json()
    assert updated_artifact["current_version"]["version"] == 2
    assert updated_artifact["current_version"]["payload"]["objective"] == "先完成第一章的结构"


def test_ai_proposal_flow(client, project):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "讨论", "unit_id": None},
    )
    assert conversation.status_code == 201
    assert client.get(f"/api/conversations/{conversation.json()['id']}").status_code == 200
    assert client.get("/api/episodes").status_code == 404
    assert client.get("/api/series").status_code == 404


def test_assets_roundtrip(client, project):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={"kind": "reference", "name": "参考", "uri": "media/x.png", "mime_type": "image/png"},
    )
    assert asset.status_code == 201
    assert client.get(f"/api/projects/{project['id']}/assets").json()["items"][0]["name"] == "参考"


def test_provider_api_keys_are_masked(client):
    providers = client.get("/api/provider-profiles").json()
    for provider in providers:
        if provider["api_key"]:
            assert "***" in provider["api_key"]
            assert len(provider["api_key"]) < 32


@respx.mock
def test_provider_model_discovery_uses_grok_v1_and_normalizes(client):
    upstream = respx.get("http://upstream.test/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "zeta-video", "name": "Zeta Video", "owned_by": "demo"},
                    {"model_id": "alpha-chat", "display_name": "Alpha Chat"},
                    "middle-image",
                    {"id": "zeta-video", "name": "duplicate must be ignored"},
                    {"unknown": "ignored"},
                ]
            },
        )
    )

    response = client.post(
        "/api/provider-profiles/discover-models",
        json={
            "capability_type": "video",
            "adapter": "grok2api",
            "base_url": "http://upstream.test",
            "api_key": "secret-key",
            "settings": {},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"model_id": "alpha-chat", "name": "Alpha Chat", "owned_by": "", "capability_type": "llm"},
            {"model_id": "middle-image", "name": "middle-image", "owned_by": "", "capability_type": "image"},
            {"model_id": "zeta-video", "name": "Zeta Video", "owned_by": "demo", "capability_type": "video"},
        ],
        "source_url": "http://upstream.test/v1/models",
    }
    assert upstream.called
    assert upstream.calls.last.request.headers["Authorization"] == "Bearer secret-key"


@respx.mock
def test_provider_model_discovery_reuses_saved_key_and_advanced_settings(client):
    created = client.post(
        "/api/provider-profiles",
        json={
            "name": "Custom upstream",
            "capability_type": "llm",
            "adapter": "custom",
            "base_url": "http://upstream.test/api",
            "api_key": "stored-secret",
            "settings": {},
            "models": [{"model_id": "manual-model", "capability_type": "llm"}],
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    upstream = respx.get("http://upstream.test/catalog/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "actual-model"}]})
    )

    response = client.post(
        "/api/provider-profiles/discover-models",
        json={
            "provider_id": provider_id,
            "capability_type": "llm",
            "adapter": "custom",
            "base_url": "http://upstream.test/api",
            "api_key": "",
            "settings": {
                "models_path": "/catalog/models",
                "headers": {"X-Tenant": "studio"},
                "api_key_header": "X-API-Key",
                "api_key_scheme": "",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == [
        {"model_id": "actual-model", "name": "actual-model", "owned_by": "", "capability_type": "llm"}
    ]
    request = upstream.calls.last.request
    assert request.headers["X-Tenant"] == "studio"
    assert request.headers["X-API-Key"] == "stored-secret"
    assert "stored-secret" not in response.text


@respx.mock
def test_provider_model_discovery_infers_grok_capabilities(client):
    upstream = respx.get("http://upstream.test/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "grok-4.5"},
                    {"id": "grok-imagine-image"},
                    {"id": "grok-imagine-image-lite"},
                    {"id": "grok-imagine-video"},
                    {"id": "grok-chat-fast"},
                ]
            },
        )
    )

    response = client.post(
        "/api/provider-profiles/discover-models",
        json={
            "capability_type": "video",
            "adapter": "grok2api",
            "base_url": "http://upstream.test",
            "api_key": "secret-key",
            "settings": {},
        },
    )

    assert response.status_code == 200
    assert [
        (item["model_id"], item["capability_type"]) for item in response.json()["models"]
    ] == [
        ("grok-4.5", "llm"),
        ("grok-chat-fast", "llm"),
        ("grok-imagine-image", "image"),
        ("grok-imagine-image-lite", "image"),
        ("grok-imagine-video", "video"),
    ]
    assert upstream.called


def test_provider_models_can_be_replaced_without_overwriting_saved_key(client):
    created = client.post(
        "/api/provider-profiles",
        json={
            "name": "Editable",
            "capability_type": "llm",
            "adapter": "openai",
            "base_url": "http://upstream.test/v1",
            "api_key": "original-secret",
            "models": [{"model_id": "old-model", "capability_type": "llm"}],
        },
    )
    provider_id = created.json()["id"]

    updated = client.patch(
        f"/api/provider-profiles/{provider_id}",
        json={
            "api_key": "",
            "models": [
                {"name": "New Model", "model_id": "new-model", "capability_type": "llm"}
            ],
        },
    )

    assert updated.status_code == 200
    assert [model["model_id"] for model in updated.json()["models"]] == ["new-model"]
    assert updated.json()["api_key"].startswith("orig")
    assert "***" in updated.json()["api_key"]


def test_provider_default_model_wins_across_providers(app):
    with TestClient(app) as client:
        first = client.post(
            "/api/provider-profiles",
            json={
                "name": "A-LLM",
                "capability_type": "llm",
                "adapter": "openai",
                "base_url": "http://upstream.test/v1",
                "models": [
                    {"model_id": "a-1", "capability_type": "llm"},
                    {"model_id": "a-2", "capability_type": "llm"},
                ],
            },
        )
        second = client.post(
            "/api/provider-profiles",
            json={
                "name": "B-LLM",
                "capability_type": "llm",
                "adapter": "openai",
                "base_url": "http://upstream.test/v1",
                "models": [
                    {"model_id": "b-1", "capability_type": "llm"},
                    {"model_id": "b-2", "capability_type": "llm"},
                ],
            },
        )
        assert first.status_code == 201
        assert second.status_code == 201
        first_id = first.json()["id"]
        second_id = second.json()["id"]

        # 未设置默认时沿用“第一个匹配”的旧行为
        with UnitOfWork(app.state.database) as uow:
            provider = provider_for_capability(uow, "llm")
            assert provider["id"] == first_id
            assert provider["models"][0]["model_id"] == "a-1"

        # 在第二个渠道里把 b-2 标为默认，选择结果应切到 B 且 b-2 排第一
        updated = client.patch(
            f"/api/provider-profiles/{second_id}",
            json={
                "models": [
                    {"model_id": "b-1", "capability_type": "llm"},
                    {"model_id": "b-2", "capability_type": "llm", "is_default": True},
                ]
            },
        )
        assert updated.status_code == 200

        with UnitOfWork(app.state.database) as uow:
            provider = provider_for_capability(uow, "llm")
            assert provider["id"] == second_id
            assert [model["model_id"] for model in provider["models"]] == ["b-2", "b-1"]

        overview = client.get("/api/model-capabilities").json()
        default_rows = [item for item in overview if item["is_default"]]
        assert [item["model_id"] for item in default_rows] == ["b-2"]


def test_default_model_flag_is_preferred_by_adapters():
    provider = {
        "capability_type": "llm",
        "models": [
            {"model_id": "a", "capability_type": "llm"},
            {"model_id": "b", "capability_type": "llm", "is_default": True},
        ],
    }
    assert _pick_llm_model(provider) == "b"

    image_provider = {
        "models": [
            {"model_id": "img-1", "capability_type": "image"},
            {"model_id": "img-2", "capability_type": "image", "is_default": True},
        ]
    }
    assert _model(image_provider) == "img-2"
    assert _model(image_provider, "img-1") == "img-1"


def test_sse_uses_default_message_event():
    from app.api.routes.conversations import _sse

    payload = _sse({"id": "turn:1", "type": "token", "text": "你好"})
    assert "event:" not in payload
    assert '"type": "token"' in payload
    assert '"text": "你好"' in payload


def test_turn_stream_replays_done_for_completed_turn(app, project):
    with TestClient(app) as client:
        with UnitOfWork(app.state.database) as uow:
            conversation = uow.conversations.create(project["id"], None, "流式回归")
            turn = uow.agent_turns.create(conversation["id"], project["id"])
            uow.agent_turns.set_status(turn["id"], "succeeded")
            conversation_id = conversation["id"]
            turn_id = turn["id"]

        response = client.get(
            f"/api/conversations/{conversation_id}/stream?turn_id={turn_id}"
        )
        assert response.status_code == 200
        body = response.text
        assert '"type": "done"' in body
        assert '"failed": false' in body
        assert "event: done" not in body


def test_creative_brief_accepts_plain_string_platforms_and_constraints():
    from app.domain import CreativeBrief

    brief = CreativeBrief.model_validate(
        {
            "title": "测试",
            "platforms": ["Bilibili", "抖音"],
            "constraints": ["必须还原原著经典角色设定", "版权合规"],
        }
    )
    assert [item.platform for item in brief.platforms] == ["Bilibili", "抖音"]
    assert [item.kind for item in brief.constraints] == ["custom", "custom"]
    assert [item.value for item in brief.constraints] == [
        "必须还原原著经典角色设定",
        "版权合规",
    ]


def test_accept_brief_proposal_with_plain_string_platforms(app, project):
    with TestClient(app) as client:
        with UnitOfWork(app.state.database) as uow:
            proposal = uow.proposals.create(
                {
                    "project_id": project["id"],
                    "artifact_kind": "brief",
                    "title": "更新 Brief",
                    "rationale": "平台/约束是字符串",
                    "proposed_payload": {
                        "platforms": ["Bilibili", "抖音"],
                        "constraints": ["版权合规", "必须还原经典角色"],
                    },
                }
            )
            proposal_id = proposal["id"]

        response = client.post(f"/api/proposals/{proposal_id}/accept", json={})
        assert response.status_code == 200

        detail = client.get(f"/api/projects/{project['id']}").json()
        assert detail["brief"]["platforms"][0]["platform"] == "Bilibili"
        assert detail["brief"]["constraints"][0]["value"] == "版权合规"

