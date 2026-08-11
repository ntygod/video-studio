from app.application.commands.recovery import (
    recover_interrupted_operations,
)
from app.store import UnitOfWork


def _upload(client, project_id: str):
    response = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={
            "file": (
                "note.txt",
                b"durable asset",
                "text/plain",
            )
        },
        data={"name": "待删除素材"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_asset_delete_is_idempotent_audited_and_quarantined(
    app,
    client,
    project,
):
    asset = _upload(client, project["id"])
    original = app.state.media_store.path_for(asset["uri"])
    assert original.exists()
    headers = {"Idempotency-Key": "delete-asset-once"}

    first = client.delete(
        f"/api/assets/{asset['id']}",
        headers=headers,
    )
    second = client.delete(
        f"/api/assets/{asset['id']}",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert client.get(f"/api/assets/{asset['id']}").status_code == 404
    assert not original.exists()

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "delete-asset-once"
        )
    assert operation["operation_type"] == "asset.delete"
    assert operation["status"] == "succeeded"
    assert operation["inverse_operation"] is None
    quarantined = (
        app.state.media_store.root
        / ".trash"
        / operation["id"]
        / asset["uri"]
    )
    assert quarantined.exists()


def test_asset_with_derivative_cannot_be_deleted(
    client,
    project,
):
    parent = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "name": "parent",
            "uri": "external/parent.png",
        },
    ).json()
    child = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "name": "child",
            "uri": "external/child.png",
            "parent_asset_id": parent["id"],
        },
    )
    assert child.status_code == 201

    response = client.delete(
        f"/api/assets/{parent['id']}",
        headers={"Idempotency-Key": "blocked-delete"},
    )
    assert response.status_code == 409
    assert client.get(f"/api/assets/{parent['id']}").status_code == 200


def test_interrupted_asset_delete_restores_quarantined_file(
    app,
    project,
):
    uri, sha256 = app.state.media_store.write_bytes(
        project["id"],
        b"restore me",
        ".bin",
    )
    with UnitOfWork(app.state.database) as uow:
        asset = uow.assets.create(
            {
                "project_id": project["id"],
                "kind": "reference",
                "name": "recover",
                "uri": uri,
                "mime_type": "application/octet-stream",
                "sha256": sha256,
            }
        )
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "asset.delete",
                "target_type": "asset",
                "target_id": asset["id"],
                "arguments": {"asset_id": asset["id"]},
                "preconditions": [],
            }
        )

    moved = app.state.media_store.quarantine_asset(
        [uri],
        operation["id"],
    )
    assert moved == [uri]
    assert not app.state.media_store.path_for(uri).exists()

    recovered = recover_interrupted_operations(
        app.state.database,
        media_store=app.state.media_store,
    )
    assert recovered == 1
    assert app.state.media_store.path_for(uri).exists()
    with UnitOfWork(app.state.database) as uow:
        assert uow.assets.get(asset["id"])["uri"] == uri
        failed = uow.operations.get(operation["id"])
    assert failed["status"] == "failed"
