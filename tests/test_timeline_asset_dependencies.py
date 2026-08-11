def test_timeline_registers_first_class_asset_dependencies(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "image",
            "name": "时间线素材",
            "uri": f"{project['id']}/timeline.png",
            "mime_type": "image/png",
            "metadata": {"width": 100, "height": 100},
        },
    ).json()

    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={},
        headers={"Idempotency-Key": "timeline-asset-edge"},
    )
    assert compiled.status_code == 200, compiled.text
    artifact = compiled.json()["artifact"]
    version_id = artifact["current_version"]["id"]

    dependencies = client.get(
        f"/api/artifacts/{artifact['id']}/asset-dependencies"
    )
    assert dependencies.status_code == 200
    assert len(dependencies.json()) == 1
    edge = dependencies.json()[0]
    assert edge["upstream_asset_id"] == asset["id"]
    assert edge["downstream_version_id"] == version_id
    assert edge["dependency_type"] == "timeline_clip"
    assert edge["asset_exists"] is True
    assert edge["upstream_asset"]["name"] == "时间线素材"

    dependents = client.get(
        f"/api/assets/{asset['id']}/dependents"
    )
    assert dependents.status_code == 200
    assert [item["downstream_artifact_id"] for item in dependents.json()] == [
        artifact["id"]
    ]

    provenance = client.get(
        f"/api/artifact-versions/{version_id}/provenance"
    ).json()
    assert [
        item["upstream_asset_id"]
        for item in provenance["asset_dependencies"]
    ] == [asset["id"]]
