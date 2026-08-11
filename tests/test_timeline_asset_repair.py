def _asset(
    client,
    project_id: str,
    name: str,
    *,
    kind: str = "image",
    unit_id: str | None = None,
):
    response = client.post(
        f"/api/projects/{project_id}/assets",
        json={
            "unit_id": unit_id,
            "kind": kind,
            "name": name,
            "uri": f"{project_id}/{name}.bin",
            "mime_type": (
                "video/mp4" if kind == "video" else "image/png"
            ),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _blocked_timeline(client, project_id: str):
    old = _asset(client, project_id, "旧素材")
    compiled = client.post(
        f"/api/projects/{project_id}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "repair-source-timeline"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]
    deleted = client.delete(f"/api/assets/{old['id']}")
    assert deleted.status_code == 200, deleted.text
    freshness = client.get(
        f"/api/artifacts/{timeline['id']}/freshness"
    ).json()
    assert freshness["status"] == "blocked"
    return old, timeline


def test_repair_timeline_replaces_missing_asset_and_appends_once(
    client,
    project,
):
    old, timeline = _blocked_timeline(client, project["id"])
    replacement = _asset(client, project["id"], "新素材")
    body = {
        "expected_current_version_id": (
            timeline["current_version"]["id"]
        ),
        "replacements": {old["id"]: replacement["id"]},
    }
    first = client.post(
        f"/api/artifacts/{timeline['id']}/repair-assets",
        json=body,
    )
    second = client.post(
        f"/api/artifacts/{timeline['id']}/repair-assets",
        json=body,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["artifact"]["current_version"]["id"] == (
        first.json()["artifact"]["current_version"]["id"]
    )

    repaired = first.json()["artifact"]
    assert repaired["id"] == timeline["id"]
    assert repaired["current_version"]["version"] == 2
    assert client.get(
        f"/api/artifacts/{timeline['id']}/freshness"
    ).json()["status"] == "fresh"

    dependencies = client.get(
        f"/api/artifacts/{timeline['id']}/asset-dependencies"
    ).json()
    current_edges = [
        edge
        for edge in dependencies
        if edge["downstream_version_id"]
        == repaired["current_version"]["id"]
    ]
    assert [edge["upstream_asset_id"] for edge in current_edges] == [
        replacement["id"]
    ]
    old_edges = [
        edge
        for edge in dependencies
        if edge["upstream_asset_id"] == old["id"]
    ]
    assert len(old_edges) == 1
    assert old_edges[0]["asset_exists"] is False


def test_repair_timeline_requires_all_missing_assets(
    client,
    project,
):
    first_asset = _asset(client, project["id"], "素材一")
    second_asset = _asset(client, project["id"], "素材二")
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "repair-two-assets"},
    ).json()["artifact"]
    assert client.delete(
        f"/api/assets/{first_asset['id']}"
    ).status_code == 200
    assert client.delete(
        f"/api/assets/{second_asset['id']}"
    ).status_code == 200
    replacement = _asset(client, project["id"], "只替换一个")

    response = client.post(
        f"/api/artifacts/{compiled['id']}/repair-assets",
        json={
            "expected_current_version_id": (
                compiled["current_version"]["id"]
            ),
            "replacements": {
                first_asset["id"]: replacement["id"]
            },
        },
    )
    assert response.status_code == 422
    assert second_asset["id"] in response.json()["detail"]


def test_repair_timeline_rejects_incompatible_asset_kind(
    client,
    project,
):
    old, timeline = _blocked_timeline(client, project["id"])
    voice = _asset(
        client,
        project["id"],
        "错误类型",
        kind="voice",
    )
    response = client.post(
        f"/api/artifacts/{timeline['id']}/repair-assets",
        json={
            "expected_current_version_id": (
                timeline["current_version"]["id"]
            ),
            "replacements": {old["id"]: voice["id"]},
        },
    )
    assert response.status_code == 409
    assert "incompatible" in response.json()["detail"]


def test_repair_timeline_rejects_stale_expected_version(
    client,
    project,
):
    old, timeline = _blocked_timeline(client, project["id"])
    replacement = _asset(client, project["id"], "替代素材")
    changed = client.post(
        f"/api/artifacts/{timeline['id']}/versions",
        json={"payload": timeline["current_version"]["payload"]},
    )
    assert changed.status_code == 201, changed.text

    response = client.post(
        f"/api/artifacts/{timeline['id']}/repair-assets",
        json={
            "expected_current_version_id": (
                timeline["current_version"]["id"]
            ),
            "replacements": {old["id"]: replacement["id"]},
        },
    )
    assert response.status_code == 409
    assert "changed" in response.json()["detail"]
