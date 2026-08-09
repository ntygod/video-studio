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
    assert len(detail["units"]) == 5
    assert {unit["unit_type"] for unit in detail["units"]} == {"volume", "chapter", "season", "variant", "whatever"}
    assert not detail["brief"]["platforms"]
    assert not detail["settings"]["delivery_profiles"]


def test_artifact_versions_are_append_only(client, project):
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
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
    brief_artifact = next(item for item in detail["artifacts"] if item["kind"] == "brief")
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


def test_workflows_and_assets(client, project):
    workflows = client.get("/api/workflows")
    assert workflows.status_code == 200
    assert len(workflows.json()) >= 3
    custom = client.post(
        "/api/workflows",
        json={
            "name": "自定义研究流程",
            "definition": {
                "version": "1",
                "entry_nodes": ["research"],
                "nodes": {
                    "research": {
                        "key": "research",
                        "kind": "llm",
                        "required_capability": "llm",
                        "prompt": "调研",
                    }
                },
                "edges": [],
            },
        },
    )
    assert custom.status_code == 201
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={"kind": "reference", "name": "参考", "uri": "media/x.png", "mime_type": "image/png"},
    )
    assert asset.status_code == 201
    assert client.get(f"/api/projects/{project['id']}/assets").json()[0]["name"] == "参考"


def test_provider_api_keys_are_masked(client):
    providers = client.get("/api/provider-profiles").json()
    for provider in providers:
        if provider["api_key"]:
            assert "***" in provider["api_key"]
            assert len(provider["api_key"]) < 32

