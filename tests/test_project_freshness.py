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


def test_project_freshness_defaults_to_actionable_items(
    client,
    project,
):
    source = _artifact(client, project["id"], "上游")
    downstream = _artifact(client, project["id"], "下游")
    registered = client.post(
        "/api/artifact-versions/"
        f"{downstream['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                source["current_version"]["id"]
            ]
        },
        headers={
            "Idempotency-Key": "project-freshness-edge"
        },
    )
    assert registered.status_code == 201, registered.text

    initial = client.get(
        f"/api/projects/{project['id']}/artifact-freshness"
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["items"] == []
    assert initial.json()["counts"]["fresh"] >= 4

    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "上游 v2"}},
    )
    assert updated.status_code == 201, updated.text

    response = client.get(
        f"/api/projects/{project['id']}/artifact-freshness"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["stale"] == 1
    assert [item["artifact_id"] for item in body["items"]] == [
        downstream["id"]
    ]
    item = body["items"][0]
    assert item["name"] == "下游"
    assert item["kind"] == "generated"
    assert item["status"] == "stale"
    assert item["current_version_id"] == (
        downstream["current_version"]["id"]
    )
    assert updated.json()["id"] in item[
        "stale_from_version_ids"
    ]


def test_project_freshness_can_include_fresh_items(
    client,
    project,
):
    response = client.get(
        f"/api/projects/{project['id']}/artifact-freshness",
        params={"include_fresh": "true"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == sum(body["counts"].values())
    assert {item["status"] for item in body["items"]} == {
        "fresh"
    }


def test_project_freshness_requires_existing_project(client):
    response = client.get(
        "/api/projects/not-found/artifact-freshness"
    )
    assert response.status_code == 404
