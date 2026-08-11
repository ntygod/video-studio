from app.application.commands.recovery import recover_interrupted_operations
from app.store import UnitOfWork


def test_unit_subtree_delete_is_idempotent_and_quarantines_media(
    app,
    client,
    project,
):
    parent = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "父节点"}]},
    ).json()[0]
    child = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "子节点", "parent_id": parent["id"]}]},
    ).json()[0]
    upload = client.post(
        f"/api/projects/{project['id']}/assets/upload",
        files={"file": ("child.txt", b"child media", "text/plain")},
        data={"unit_id": child["id"]},
    ).json()
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "unit_id": child["id"], "kind": "generated",
            "name": "子稿件", "payload": {"body": "x"},
        },
    ).json()
    original = app.state.media_store.path_for(upload["uri"])
    headers = {"Idempotency-Key": "delete-unit-tree-once"}

    first = client.delete(
        f"/api/projects/{project['id']}/units/{parent['id']}",
        headers=headers,
    )
    second = client.delete(
        f"/api/projects/{project['id']}/units/{parent['id']}",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert client.get(
        f"/api/projects/{project['id']}/units/{parent['id']}"
    ).status_code == 404
    assert client.get(
        f"/api/projects/{project['id']}/units/{child['id']}"
    ).status_code == 404
    assert client.get(f"/api/assets/{upload['id']}").status_code == 404
    assert client.get(f"/api/artifacts/{artifact['id']}").status_code == 404
    assert not original.exists()

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "delete-unit-tree-once"
        )
    assert operation["operation_type"] == "unit.delete"
    assert operation["status"] == "succeeded"
    assert {item["id"] for item in first.json()["deleted_units"]} == {
        parent["id"], child["id"]
    }
    assert operation["inverse_operation"] is None


def test_unit_delete_precondition_blocks_changed_root(
    app,
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "会变化"}]},
    ).json()[0]
    response = client.delete(
        f"/api/projects/{project['id']}/units/{unit['id']}",
        params={"expected_updated_at": unit["updated_at"] + 1},
        headers={"Idempotency-Key": "unit-delete-conflict"},
    )
    assert response.status_code == 409
    assert client.get(
        f"/api/projects/{project['id']}/units/{unit['id']}"
    ).status_code == 200
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "unit-delete-conflict"
        )
    assert operation["status"] == "failed"


def test_interrupted_unit_delete_restores_quarantined_file(
    app,
    project,
):
    with UnitOfWork(app.state.database) as uow:
        unit = uow.units.list(project["id"])
        if unit:
            target = unit[0]
        else:
            from app.application.projects import create_units
            target = create_units(
                uow,
                project["id"],
                [{"title": "恢复节点"}],
            )[0]
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "unit.delete",
                "target_type": "unit",
                "target_id": target.id,
                "arguments": {"unit_id": target.id},
                "preconditions": [],
            }
        )
    uri, _ = app.state.media_store.write_bytes(
        project["id"], b"restore unit", ".bin", unit_id=target.id
    )
    app.state.media_store.quarantine_asset([uri], operation["id"])
    assert not app.state.media_store.path_for(uri).exists()

    recovered = recover_interrupted_operations(
        app.state.database,
        media_store=app.state.media_store,
    )
    assert recovered == 1
    assert app.state.media_store.path_for(uri).exists()
    with UnitOfWork(app.state.database) as uow:
        assert uow.units.get(target.id).id == target.id
        assert uow.operations.get(operation["id"])["status"] == "failed"
