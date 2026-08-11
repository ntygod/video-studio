from app.store import UnitOfWork


def test_project_creation_is_idempotent_and_cross_entity_audited(
    client,
):
    headers = {"Idempotency-Key": "project-create-once"}
    body = {
        "title": "可靠项目",
        "project_type": "video",
        "concept": "一次创建",
    }

    first = client.post(
        "/api/projects",
        json=body,
        headers=headers,
    )
    second = client.post(
        "/api/projects",
        json=body,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    project_id = first.json()["id"]
    matching_projects = [
        item
        for item in client.get("/api/projects").json()
        if item["id"] == project_id
    ]
    assert len(matching_projects) == 1

    operations = client.get(
        f"/api/projects/{project_id}/operations"
    ).json()
    operation = next(
        item
        for item in operations
        if item["idempotency_key"] == "project-create-once"
    )
    assert operation["operation_type"] == "project.create"
    assert operation["status"] == "succeeded"
    assert operation["result"]["id"] == project_id
    affected_types = [
        item["type"]
        for item in operation["affected_entities"]
    ]
    assert affected_types.count("project") == 1
    assert affected_types.count("artifact") == 2
    assert affected_types.count("artifact_version") == 2


def test_project_patch_has_revision_precondition_and_snapshot_replay(
    client,
    project,
):
    headers = {"Idempotency-Key": "project-patch-v2"}
    request_body = {
        "expected_revision": project["revision"],
        "patch": {"title": "第二版标题"},
    }
    first = client.patch(
        f"/api/projects/{project['id']}",
        json=request_body,
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == project["revision"] + 1

    later = client.patch(
        f"/api/projects/{project['id']}",
        json={
            "expected_revision": first.json()["revision"],
            "patch": {"title": "第三版标题"},
        },
    )
    assert later.status_code == 200, later.text

    replay = client.patch(
        f"/api/projects/{project['id']}",
        json=request_body,
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    stale = client.patch(
        f"/api/projects/{project['id']}",
        headers={"Idempotency-Key": "project-stale"},
        json={
            "expected_revision": project["revision"],
            "patch": {"title": "不应写入"},
        },
    )
    assert stale.status_code == 409
    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "project-stale"
        )
    assert operation["status"] == "failed"
    assert "revision changed" in operation["error"]


def test_unit_batch_is_idempotent(client, project):
    headers = {"Idempotency-Key": "units-once"}
    body = {
        "units": [
            {"id": "chapter-a", "title": "第一章"},
            {"id": "chapter-b", "title": "第二章"},
        ]
    }
    first = client.post(
        f"/api/projects/{project['id']}/units",
        json=body,
        headers=headers,
    )
    second = client.post(
        f"/api/projects/{project['id']}/units",
        json=body,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    page = client.get(
        f"/api/projects/{project['id']}/units",
        params={"limit": 100},
    ).json()
    assert {item["id"] for item in page["items"]} == {
        "chapter-a",
        "chapter-b",
    }


def test_unit_patch_rejects_cycle_and_replays_snapshot(
    client,
    project,
):
    created = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"id": "parent", "title": "父"},
                {
                    "id": "child",
                    "title": "子",
                    "parent_id": "parent",
                },
            ]
        },
    ).json()
    parent = next(item for item in created if item["id"] == "parent")

    cycle = client.patch(
        f"/api/projects/{project['id']}/units/parent",
        headers={"Idempotency-Key": "unit-cycle"},
        json={"parent_id": "child"},
    )
    assert cycle.status_code == 409
    with UnitOfWork(client.app.state.database) as uow:
        assert uow.units.get("parent").parent_id is None
        failed = uow.operations.find_by_idempotency_key(
            "unit-cycle"
        )
    assert failed["status"] == "failed"

    headers = {"Idempotency-Key": "unit-patch-once"}
    first = client.patch(
        f"/api/projects/{project['id']}/units/parent",
        headers=headers,
        params={"expected_updated_at": parent["updated_at"]},
        json={"title": "父节点第二版"},
    )
    assert first.status_code == 200, first.text
    later = client.patch(
        f"/api/projects/{project['id']}/units/parent",
        json={"title": "父节点第三版"},
    )
    assert later.status_code == 200
    replay = client.patch(
        f"/api/projects/{project['id']}/units/parent",
        headers=headers,
        params={"expected_updated_at": parent["updated_at"]},
        json={"title": "父节点第二版"},
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()


def test_unit_batch_accepts_forward_parent_references(
    client,
    project,
):
    response = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {
                    "id": "child-first",
                    "title": "子",
                    "parent_id": "parent-later",
                },
                {"id": "parent-later", "title": "父"},
            ]
        },
    )
    assert response.status_code == 201, response.text
    assert [item["id"] for item in response.json()] == [
        "child-first",
        "parent-later",
    ]
    with UnitOfWork(client.app.state.database) as uow:
        assert (
            uow.units.get("child-first").parent_id
            == "parent-later"
        )


def test_invalid_semantic_patch_is_422_and_audited(
    client,
    project,
):
    response = client.patch(
        f"/api/projects/{project['id']}",
        headers={"Idempotency-Key": "bad-project-patch"},
        json={
            "expected_revision": project["revision"],
            "patch": {"unknown_field": True},
        },
    )
    assert response.status_code == 422
    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "bad-project-patch"
        )
    assert operation["status"] == "failed"
    assert "unsupported project patch fields" in operation["error"]


def test_unit_batch_cycle_rolls_back_atomically(
    client,
    project,
):
    response = client.post(
        f"/api/projects/{project['id']}/units",
        headers={"Idempotency-Key": "unit-batch-cycle"},
        json={
            "units": [
                {
                    "id": "cycle-a",
                    "title": "A",
                    "parent_id": "cycle-b",
                },
                {
                    "id": "cycle-b",
                    "title": "B",
                    "parent_id": "cycle-a",
                },
            ]
        },
    )
    assert response.status_code == 409
    with UnitOfWork(client.app.state.database) as uow:
        ids = {
            item.id
            for item in uow.units.list(project["id"])
        }
        operation = uow.operations.find_by_idempotency_key(
            "unit-batch-cycle"
        )
    assert "cycle-a" not in ids
    assert "cycle-b" not in ids
    assert operation["status"] == "failed"
