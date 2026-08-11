from app.store import UnitOfWork


def test_asset_create_is_idempotent_and_audited(
    client,
    project,
):
    headers = {"Idempotency-Key": "asset-create-once"}
    body = {
        "kind": "reference",
        "name": "参考图",
        "uri": "media/reference.png",
        "mime_type": "image/png",
        "generation": {"prompt": "small"},
        "metadata": {"width": 100},
    }

    first = client.post(
        f"/api/projects/{project['id']}/assets",
        headers=headers,
        json=body,
    )
    second = client.post(
        f"/api/projects/{project['id']}/assets",
        headers=headers,
        json=body,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    page = client.get(
        f"/api/projects/{project['id']}/assets",
        params={"limit": 100},
    ).json()
    matching = [
        item
        for item in page["items"]
        if item["name"] == "参考图"
    ]
    assert len(matching) == 1

    operations = client.get(
        f"/api/projects/{project['id']}/operations"
    ).json()
    operation = next(
        item
        for item in operations
        if item["idempotency_key"] == "asset-create-once"
    )
    assert operation["operation_type"] == "asset.create"
    assert operation["status"] == "succeeded"
    assert operation["affected_entities"] == [
        {"type": "asset", "id": first.json()["id"]}
    ]
    assert "generation_sha256" in operation["arguments"]
    assert "generation" not in operation["arguments"]


def test_asset_scope_patch_can_explicitly_clear_links(
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "镜头单元"}]},
    ).json()[0]
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "unit_id": unit["id"],
            "shot_id": "shot-1",
            "kind": "reference",
            "name": "可解绑",
            "uri": "media/scope.png",
        },
    ).json()

    clear_unit = client.patch(
        f"/api/assets/{asset['id']}",
        headers={"Idempotency-Key": "asset-clear-unit"},
        json={"unit_id": None},
    )
    assert clear_unit.status_code == 200, clear_unit.text
    assert clear_unit.json()["unit_id"] is None
    assert clear_unit.json()["shot_id"] == "shot-1"

    clear_shot = client.patch(
        f"/api/assets/{asset['id']}",
        json={"shot_id": None},
    )
    assert clear_shot.status_code == 200
    assert clear_shot.json()["unit_id"] is None
    assert clear_shot.json()["shot_id"] is None


def test_empty_asset_patch_is_422_and_audited(
    client,
    project,
):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "name": "empty patch",
            "uri": "media/empty.png",
        },
    ).json()

    response = client.patch(
        f"/api/assets/{asset['id']}",
        headers={"Idempotency-Key": "empty-asset-patch"},
        json={},
    )
    assert response.status_code == 422

    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "empty-asset-patch"
        )
    assert operation["status"] == "failed"
    assert "must include unit_id or shot_id" in operation["error"]


def test_asset_cannot_bind_to_unit_from_another_project(
    client,
    project,
):
    other = client.post(
        "/api/projects",
        json={"title": "其他项目"},
    ).json()
    foreign_unit = client.post(
        f"/api/projects/{other['id']}/units",
        json={"units": [{"title": "外部单元"}]},
    ).json()[0]
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "name": "本项目素材",
            "uri": "media/local.png",
        },
    ).json()

    response = client.patch(
        f"/api/assets/{asset['id']}",
        headers={"Idempotency-Key": "foreign-unit"},
        json={"unit_id": foreign_unit["id"]},
    )
    assert response.status_code == 404
    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "foreign-unit"
        )
        unchanged = uow.assets.get(asset["id"])
    assert operation["status"] == "failed"
    assert unchanged["unit_id"] is None
