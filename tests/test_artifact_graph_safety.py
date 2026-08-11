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


def _register(client, output_version_id: str, input_ids: list[str], key: str):
    return client.post(
        f"/api/artifact-versions/{output_version_id}/derivation",
        json={"input_version_ids": input_ids},
        headers={"Idempotency-Key": key},
    )


def test_artifact_cannot_depend_on_its_own_previous_version(
    client,
    project,
):
    artifact = _artifact(client, project["id"], "自依赖")
    first = artifact["current_version"]["id"]
    second = client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        json={"payload": {"body": "v2"}},
    ).json()
    response = _register(
        client,
        second["id"],
        [first],
        "self-cycle",
    )
    assert response.status_code == 409
    assert "itself" in response.json()["detail"]


def test_artifact_dependency_rejects_direct_cycle(
    client,
    project,
):
    left = _artifact(client, project["id"], "A")
    right = _artifact(client, project["id"], "B")
    first = _register(
        client,
        right["current_version"]["id"],
        [left["current_version"]["id"]],
        "edge-a-b",
    )
    assert first.status_code == 201, first.text

    left_v2 = client.post(
        f"/api/artifacts/{left['id']}/versions",
        json={"payload": {"body": "A v2"}},
    ).json()
    cycle = _register(
        client,
        left_v2["id"],
        [right["current_version"]["id"]],
        "edge-b-a",
    )
    assert cycle.status_code == 409
    assert "cycle" in cycle.json()["detail"]
    with UnitOfWork(client.app.state.database) as uow:
        derivation = uow.artifact_graph.derivation(left_v2["id"])
    assert derivation["dependencies"] == []
    assert derivation["provenance"] is None


def test_artifact_dependency_rejects_indirect_cycle(
    client,
    project,
):
    a = _artifact(client, project["id"], "A")
    b = _artifact(client, project["id"], "B")
    c = _artifact(client, project["id"], "C")
    assert _register(
        client,
        b["current_version"]["id"],
        [a["current_version"]["id"]],
        "edge-a-b-indirect",
    ).status_code == 201
    assert _register(
        client,
        c["current_version"]["id"],
        [b["current_version"]["id"]],
        "edge-b-c-indirect",
    ).status_code == 201
    a_v2 = client.post(
        f"/api/artifacts/{a['id']}/versions",
        json={"payload": {"body": "A v2"}},
    ).json()
    response = _register(
        client,
        a_v2["id"],
        [c["current_version"]["id"]],
        "edge-c-a-indirect",
    )
    assert response.status_code == 409
    assert "cycle" in response.json()["detail"]


def test_project_dependency_edge_limit_is_enforced(
    client,
    project,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.store.semantic_graph_repository."
        "MAX_PROJECT_ARTIFACT_DEPENDENCIES",
        1,
    )
    a = _artifact(client, project["id"], "A")
    b = _artifact(client, project["id"], "B")
    c = _artifact(client, project["id"], "C")
    d = _artifact(client, project["id"], "D")
    assert _register(
        client,
        b["current_version"]["id"],
        [a["current_version"]["id"]],
        "limit-first-edge",
    ).status_code == 201
    response = _register(
        client,
        d["current_version"]["id"],
        [c["current_version"]["id"]],
        "limit-second-edge",
    )
    assert response.status_code == 409
    assert "safety limit" in response.json()["detail"]
