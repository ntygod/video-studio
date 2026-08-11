def _artifact(
    client,
    project_id: str,
    name: str,
    *,
    unit_id: str | None = None,
):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "unit_id": unit_id,
            "kind": "generated",
            "name": name,
            "payload": {"body": name},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_deleting_timeline_asset_blocks_current_timeline(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "会被删除的素材",
            "uri": f"{project['id']}/missing.png",
            "mime_type": "image/png",
        },
    ).json()
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "compile-before-delete"},
    )
    assert compiled.status_code == 200, compiled.text
    timeline = compiled.json()["artifact"]

    deleted = client.delete(f"/api/assets/{asset['id']}")
    assert deleted.status_code == 200, deleted.text

    freshness = client.get(
        f"/api/artifacts/{timeline['id']}/freshness"
    ).json()
    assert freshness["status"] == "blocked"
    assert freshness["blocked_by_asset_ids"] == [asset["id"]]

    project_state = client.get(
        f"/api/projects/{project['id']}/artifact-freshness"
    ).json()
    blocked = next(
        item
        for item in project_state["items"]
        if item["artifact_id"] == timeline["id"]
    )
    assert blocked["status"] == "blocked"
    assert blocked["blocked_by_asset_ids"] == [asset["id"]]

    tombstones = client.get(
        f"/api/assets/{asset['id']}/dependents"
    ).json()
    assert len(tombstones) == 1
    assert tombstones[0]["asset_exists"] is False
    assert tombstones[0]["upstream_asset"]["name"] == "会被删除的素材"


def test_missing_asset_block_propagates_to_artifact_dependents(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "reference",
            "name": "角色参考",
            "uri": f"{project['id']}/character.png",
        },
    ).json()
    first = _artifact(client, project["id"], "角色描述")
    second = _artifact(client, project["id"], "镜头方案")

    first_edge = client.post(
        "/api/artifact-versions/"
        f"{first['current_version']['id']}/derivation",
        json={"input_asset_ids": [asset["id"]]},
        headers={"Idempotency-Key": "asset-to-first"},
    )
    assert first_edge.status_code == 201, first_edge.text
    second_edge = client.post(
        "/api/artifact-versions/"
        f"{second['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                first["current_version"]["id"]
            ]
        },
        headers={"Idempotency-Key": "first-to-second"},
    )
    assert second_edge.status_code == 201, second_edge.text

    assert client.delete(
        f"/api/assets/{asset['id']}"
    ).status_code == 200
    for artifact in (first, second):
        freshness = client.get(
            f"/api/artifacts/{artifact['id']}/freshness"
        ).json()
        assert freshness["status"] == "blocked"
        assert freshness["blocked_by_asset_ids"] == [asset["id"]]


def test_deleting_unit_blocks_external_artifact_that_uses_its_asset(
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "素材单元"}]},
    ).json()[0]
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "unit_id": unit["id"],
            "kind": "reference",
            "name": "单元素材",
            "uri": f"{project['id']}/{unit['id']}/asset.png",
        },
    ).json()
    external = _artifact(client, project["id"], "项目级产物")
    edge = client.post(
        "/api/artifact-versions/"
        f"{external['current_version']['id']}/derivation",
        json={"input_asset_ids": [asset["id"]]},
        headers={"Idempotency-Key": "unit-asset-external"},
    )
    assert edge.status_code == 201, edge.text

    deleted = client.delete(
        f"/api/projects/{project['id']}/units/{unit['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    freshness = client.get(
        f"/api/artifacts/{external['id']}/freshness"
    ).json()
    assert freshness["status"] == "blocked"
    assert freshness["blocked_by_asset_ids"] == [asset["id"]]


def test_deleting_unit_blocks_external_artifact_that_uses_its_artifact(
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "剧本单元"}]},
    ).json()[0]
    source = _artifact(
        client,
        project["id"],
        "单元剧本",
        unit_id=unit["id"],
    )
    external = _artifact(client, project["id"], "项目级镜头方案")
    edge = client.post(
        "/api/artifact-versions/"
        f"{external['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                source["current_version"]["id"]
            ]
        },
        headers={"Idempotency-Key": "unit-artifact-external"},
    )
    assert edge.status_code == 201, edge.text

    deleted = client.delete(
        f"/api/projects/{project['id']}/units/{unit['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    freshness = client.get(
        f"/api/artifacts/{external['id']}/freshness"
    ).json()
    assert freshness["status"] == "blocked"
    assert source["current_version"]["id"] in freshness[
        "stale_from_version_ids"
    ]
