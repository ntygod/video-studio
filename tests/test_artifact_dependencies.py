from app.store import UnitOfWork


def _artifact(client, project_id: str, kind: str, name: str, body: str):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": kind,
            "name": name,
            "payload": {"body": body},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _derive(client, output_version_id: str, inputs: list[str], key: str):
    response = client.post(
        f"/api/artifact-versions/{output_version_id}/derivation",
        json={
            "input_version_ids": inputs,
            "provenance": {
                "provider_profile_id": "provider-test",
                "model_id": "model-test",
                "prompt_version": "prompt-v1",
                "parameters": {"temperature": 0.2},
                "seed": "42",
            },
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new_upstream_version_marks_current_downstream_stale(
    app,
    client,
    project,
):
    source = _artifact(
        client, project["id"], "script", "剧本", "v1"
    )
    output = _artifact(
        client, project["id"], "generated", "分镜", "derived"
    )
    derivation = _derive(
        client,
        output["current_version"]["id"],
        [source["current_version"]["id"]],
        "derive-output",
    )
    assert derivation["freshness"]["status"] == "fresh"

    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "v2"}},
    )
    assert updated.status_code == 201, updated.text

    freshness = client.get(
        f"/api/artifacts/{output['id']}/freshness"
    ).json()
    assert freshness["status"] == "stale"
    assert updated.json()["id"] in freshness["stale_from_version_ids"]
    impact = client.get(
        f"/api/artifacts/{source['id']}/impact"
    ).json()
    assert [item["artifact_id"] for item in impact] == [output["id"]]

    with UnitOfWork(app.state.database) as uow:
        unrelated = uow.artifact_graph.get_freshness(source["id"])
    assert unrelated["status"] == "fresh"


def test_stale_propagation_is_recursive(client, project):
    first = _artifact(client, project["id"], "script", "A", "a1")
    second = _artifact(client, project["id"], "generated", "B", "b1")
    third = _artifact(client, project["id"], "generated", "C", "c1")
    _derive(
        client,
        second["current_version"]["id"],
        [first["current_version"]["id"]],
        "derive-b",
    )
    _derive(
        client,
        third["current_version"]["id"],
        [second["current_version"]["id"]],
        "derive-c",
    )

    client.post(
        f"/api/artifacts/{first['id']}/versions",
        json={"payload": {"body": "a2"}},
    )
    assert client.get(
        f"/api/artifacts/{second['id']}/freshness"
    ).json()["status"] == "stale"
    assert client.get(
        f"/api/artifacts/{third['id']}/freshness"
    ).json()["status"] == "stale"


def test_derivation_using_old_version_is_immediately_stale(
    client,
    project,
):
    source = _artifact(
        client, project["id"], "script", "输入", "old"
    )
    old_version_id = source["current_version"]["id"]
    client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "new"}},
    )
    output = _artifact(
        client, project["id"], "generated", "输出", "result"
    )
    derivation = _derive(
        client,
        output["current_version"]["id"],
        [old_version_id],
        "derive-old-input",
    )
    assert derivation["freshness"]["status"] == "stale"


def test_provenance_records_exact_inputs(client, project):
    source = _artifact(
        client, project["id"], "script", "来源", "source"
    )
    output = _artifact(
        client, project["id"], "generated", "结果", "output"
    )
    version_id = output["current_version"]["id"]
    input_id = source["current_version"]["id"]
    _derive(client, version_id, [input_id], "derive-provenance")

    provenance = client.get(
        f"/api/artifact-versions/{version_id}/provenance"
    ).json()["provenance"]
    assert provenance["input_version_ids"] == [input_id]
    assert provenance["provider_profile_id"] == "provider-test"
    assert provenance["model_id"] == "model-test"
    assert provenance["parameters"] == {"temperature": 0.2}
