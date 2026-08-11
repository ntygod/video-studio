from app.store import UnitOfWork


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


def _operation(client, key: str):
    with UnitOfWork(client.app.state.database) as uow:
        return uow.operations.find_by_idempotency_key(key)


def _affected_ids(operation, entity_type: str) -> set[str]:
    return {
        entity["id"]
        for entity in operation["affected_entities"]
        if entity["type"] == entity_type
    }


def test_version_advance_audits_staled_downstream_artifact(
    client,
    project,
):
    source = _artifact(client, project["id"], "上游")
    downstream = _artifact(client, project["id"], "下游")
    edge = client.post(
        "/api/artifact-versions/"
        f"{downstream['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                source["current_version"]["id"]
            ]
        },
        headers={"Idempotency-Key": "audit-stale-edge"},
    )
    assert edge.status_code == 201, edge.text

    updated = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "上游 v2"}},
        headers={"Idempotency-Key": "audit-stale-impact"},
    )
    assert updated.status_code == 201, updated.text
    operation = _operation(client, "audit-stale-impact")
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact",
    )
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact_freshness",
    )


def test_asset_delete_audits_blocked_downstream_artifact(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "kind": "reference",
            "name": "参考图",
            "uri": f"{project['id']}/reference.png",
        },
    ).json()
    downstream = _artifact(client, project["id"], "依赖素材的稿件")
    edge = client.post(
        "/api/artifact-versions/"
        f"{downstream['current_version']['id']}/derivation",
        json={"input_asset_ids": [asset["id"]]},
        headers={"Idempotency-Key": "audit-asset-edge"},
    )
    assert edge.status_code == 201, edge.text

    deleted = client.delete(
        f"/api/assets/{asset['id']}",
        headers={"Idempotency-Key": "audit-asset-delete"},
    )
    assert deleted.status_code == 200, deleted.text
    operation = _operation(client, "audit-asset-delete")
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact",
    )
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact_freshness",
    )


def test_unit_delete_audits_external_blocked_artifact(
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "将删除的单元"}]},
    ).json()[0]
    source = _artifact(
        client,
        project["id"],
        "单元稿件",
        unit_id=unit["id"],
    )
    downstream = _artifact(client, project["id"], "外部稿件")
    edge = client.post(
        "/api/artifact-versions/"
        f"{downstream['current_version']['id']}/derivation",
        json={
            "input_version_ids": [
                source["current_version"]["id"]
            ]
        },
        headers={"Idempotency-Key": "audit-unit-edge"},
    )
    assert edge.status_code == 201, edge.text

    deleted = client.delete(
        f"/api/projects/{project['id']}/units/{unit['id']}",
        headers={"Idempotency-Key": "audit-unit-delete"},
    )
    assert deleted.status_code == 200, deleted.text
    operation = _operation(client, "audit-unit-delete")
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact",
    )
    assert downstream["id"] in _affected_ids(
        operation,
        "artifact_freshness",
    )
