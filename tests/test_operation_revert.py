from app.application.commands import (
    CommandBus,
    CommandContext,
    CreateJobCommand,
)
from app.store import UnitOfWork


def _operation_by_key(app, key: str):
    with UnitOfWork(app.state.database) as uow:
        return uow.operations.find_by_idempotency_key(key)


def test_revert_pristine_artifact_creation_is_idempotent(
    app,
    client,
    project,
):
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        headers={"Idempotency-Key": "revert-created-artifact"},
        json={
            "kind": "custom_note",
            "name": "可撤销稿件",
            "payload": {"body": "draft"},
        },
    ).json()
    original = _operation_by_key(
        app,
        "revert-created-artifact",
    )

    first = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    second = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert (
        client.get(f"/api/artifacts/{created['id']}").status_code
        == 404
    )

    stored = client.get(
        f"/api/operations/{original['id']}"
    ).json()
    assert stored["reverted_by_operation_id"]
    assert stored["reverted_at"] is not None


def test_revert_artifact_version_appends_compensating_version(
    app,
    client,
    project,
):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "custom_note",
            "name": "版本补偿",
            "payload": {"body": "v1"},
        },
    ).json()
    added = client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        headers={"Idempotency-Key": "add-v2-to-revert"},
        json={"payload": {"body": "v2"}},
    )
    assert added.status_code == 201
    original = _operation_by_key(app, "add-v2-to-revert")

    reverted = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    assert reverted.status_code == 200, reverted.text
    current = client.get(
        f"/api/artifacts/{artifact['id']}"
    ).json()
    assert current["current_version"]["payload"] == {
        "body": "v1"
    }
    assert current["current_version"]["version"] == 3


def test_revert_version_is_blocked_after_later_edit(
    app,
    client,
    project,
):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "custom_note",
            "name": "冲突补偿",
            "payload": {"body": "v1"},
        },
    ).json()
    client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        headers={"Idempotency-Key": "revert-conflicted-v2"},
        json={"payload": {"body": "v2"}},
    )
    client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        json={"payload": {"body": "v3"}},
    )
    original = _operation_by_key(
        app,
        "revert-conflicted-v2",
    )

    response = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    assert response.status_code == 409
    assert "later version" in response.json()["detail"]

    stored = client.get(
        f"/api/operations/{original['id']}"
    ).json()
    assert stored["reverted_by_operation_id"] is None
    current = client.get(
        f"/api/artifacts/{artifact['id']}"
    ).json()
    assert current["current_version"]["payload"] == {
        "body": "v3"
    }


def test_revert_unit_and_asset_scope_edits(
    app,
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "原单元"}]},
    ).json()[0]
    client.patch(
        f"/api/projects/{project['id']}/units/{unit['id']}",
        headers={"Idempotency-Key": "rename-unit-to-revert"},
        json={"title": "改名单元"},
    )
    unit_operation = _operation_by_key(
        app,
        "rename-unit-to-revert",
    )
    response = client.post(
        f"/api/operations/{unit_operation['id']}/revert"
    )
    assert response.status_code == 200, response.text
    restored_unit = client.get(
        f"/api/projects/{project['id']}/units/{unit['id']}"
    ).json()
    assert restored_unit["title"] == "原单元"

    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={
            "unit_id": unit["id"],
            "shot_id": "shot-1",
            "name": "scope",
            "uri": "media/revert-scope.png",
        },
    ).json()
    client.patch(
        f"/api/assets/{asset['id']}",
        headers={"Idempotency-Key": "clear-scope-to-revert"},
        json={"unit_id": None, "shot_id": None},
    )
    asset_operation = _operation_by_key(
        app,
        "clear-scope-to-revert",
    )
    response = client.post(
        f"/api/operations/{asset_operation['id']}/revert"
    )
    assert response.status_code == 200, response.text
    restored_asset = client.get(
        f"/api/assets/{asset['id']}"
    ).json()
    assert restored_asset["unit_id"] == unit["id"]
    assert restored_asset["shot_id"] == "shot-1"


def test_revert_queued_job_marks_it_canceled(
    app,
    client,
    project,
):
    result = CommandBus(app.state.database).execute(
        CreateJobCommand(
            project_id=project["id"],
            job_type="media",
            payload={"capability": "image"},
        ),
        CommandContext(
            idempotency_key="queued-job-to-revert"
        ),
    )
    response = client.post(
        f"/api/operations/{result.operation['id']}/revert"
    )
    assert response.status_code == 200, response.text
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.get(result.result["id"])
    assert job["status"] == "canceled"
    assert job["cancel_requested"] is True


def test_revert_created_unit_batch_deletes_only_pristine_units(
    app,
    client,
    project,
):
    created = client.post(
        f"/api/projects/{project['id']}/units",
        headers={"Idempotency-Key": "units-to-revert"},
        json={
            "units": [
                {"id": "revert-parent", "title": "父"},
                {
                    "id": "revert-child",
                    "title": "子",
                    "parent_id": "revert-parent",
                },
            ]
        },
    )
    assert created.status_code == 201, created.text
    original = _operation_by_key(app, "units-to-revert")

    response = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    assert response.status_code == 200, response.text
    page = client.get(
        f"/api/projects/{project['id']}/units",
        params={"limit": 100},
    ).json()
    assert {
        item["id"] for item in page["items"]
    }.isdisjoint({"revert-parent", "revert-child"})


def test_revert_project_patch_restores_snapshot_and_audits_versions(
    app,
    client,
    project,
):
    before = client.get(
        f"/api/projects/{project['id']}"
    ).json()
    changed_brief = {
        **before["brief"],
        "concept": "第二版概念",
    }
    patched = client.patch(
        f"/api/projects/{project['id']}",
        headers={"Idempotency-Key": "project-patch-to-revert"},
        json={
            "expected_revision": before["revision"],
            "patch": {
                "title": "第二版标题",
                "brief": changed_brief,
            },
        },
    )
    assert patched.status_code == 200, patched.text
    original = _operation_by_key(
        app,
        "project-patch-to-revert",
    )

    response = client.post(
        f"/api/operations/{original['id']}/revert"
    )
    assert response.status_code == 200, response.text
    restored = client.get(
        f"/api/projects/{project['id']}"
    ).json()
    assert restored["title"] == before["title"]
    assert restored["brief"]["concept"] == before["brief"]["concept"]

    revert_operation_id = (
        response.json()["operation"]["reverted_by_operation_id"]
    )
    with UnitOfWork(app.state.database) as uow:
        revert_operation = uow.operations.get(
            revert_operation_id
        )
    affected_types = {
        item["type"]
        for item in revert_operation["affected_entities"]
    }
    assert {
        "operation",
        "project",
        "artifact",
        "artifact_version",
    } <= affected_types
