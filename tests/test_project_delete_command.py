from app.application.commands.media_saga import (
    quarantine_project_directory,
)
from app.application.commands.recovery import (
    recover_interrupted_operations,
)
from app.store import UnitOfWork


def _upload(client, project_id: str):
    response = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={
            "file": (
                "project.txt",
                b"project media",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_delete_is_idempotent_and_quarantines_media(
    app,
    client,
):
    project = client.post(
        "/api/projects",
        json={"title": "待删除项目"},
    ).json()
    asset = _upload(client, project["id"])
    original = app.state.media_store.path_for(asset["uri"])
    headers = {"Idempotency-Key": "delete-project-once"}

    first = client.delete(
        f"/api/projects/{project['id']}",
        headers=headers,
    )
    second = client.delete(
        f"/api/projects/{project['id']}",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert not original.exists()

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "delete-project-once"
        )
    assert operation["operation_type"] == "project.delete"
    assert operation["status"] == "succeeded"
    assert operation["inverse_operation"] is None
    quarantined = (
        app.state.media_store.root
        / ".trash"
        / operation["id"]
        / asset["uri"]
    )
    assert quarantined.exists()


def test_project_delete_revision_precondition_is_audited(
    app,
    client,
):
    project = client.post(
        "/api/projects",
        json={"title": "版本冲突"},
    ).json()
    response = client.delete(
        f"/api/projects/{project['id']}",
        params={"expected_revision": project["revision"] + 1},
        headers={"Idempotency-Key": "project-delete-conflict"},
    )
    assert response.status_code == 409
    assert client.get(f"/api/projects/{project['id']}").status_code == 200
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "project-delete-conflict"
        )
    assert operation["status"] == "failed"


def test_interrupted_project_delete_restores_media_directory(
    app,
    project,
):
    uri, _ = app.state.media_store.write_bytes(
        project["id"],
        b"restore project",
        ".bin",
    )
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "project.delete",
                "target_type": "project",
                "target_id": project["id"],
                "arguments": {"project_id": project["id"]},
                "preconditions": [],
            }
        )

    moved = quarantine_project_directory(
        app.state.media_store,
        project["id"],
        operation["id"],
    )
    assert uri in moved
    assert not app.state.media_store.path_for(uri).exists()

    recovered = recover_interrupted_operations(
        app.state.database,
        media_store=app.state.media_store,
    )
    assert recovered == 1
    assert app.state.media_store.path_for(uri).exists()
    with UnitOfWork(app.state.database) as uow:
        assert uow.projects.get(project["id"]).id == project["id"]
        failed = uow.operations.get(operation["id"])
    assert failed["status"] == "failed"
