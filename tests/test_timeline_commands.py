from app.store import UnitOfWork


def _operation(app, project_id: str, operation_type: str):
    with UnitOfWork(app.state.database) as uow:
        return next(
            item
            for item in uow.operations.list(project_id, limit=200)
            if item["operation_type"] == operation_type
        )


def test_timeline_compile_is_idempotent_and_audited(
    app,
    client,
    project,
):
    headers = {"Idempotency-Key": "compile-project-timeline"}
    first = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None, "parameters": {"fps": 24}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None, "parameters": {"fps": 24}},
        headers=headers,
    )
    assert second.status_code == 200, second.text

    first_body = first.json()
    second_body = second.json()
    assert (
        second_body["artifact"]["current_version"]["id"]
        == first_body["artifact"]["current_version"]["id"]
    )
    assert second_body["timeline"] == first_body["timeline"]

    versions = client.get(
        f"/api/artifacts/{first_body['artifact']['id']}/versions"
    ).json()
    assert len(versions) == 1

    operation = _operation(app, project["id"], "timeline.compile")
    assert operation["status"] == "succeeded"
    assert operation["arguments"]["idempotency_scope"].startswith(
        "timeline:"
    )


def test_new_timeline_compile_can_be_reverted(
    app,
    client,
    project,
):
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
        headers={"Idempotency-Key": "compile-then-revert"},
    )
    assert compiled.status_code == 200, compiled.text
    artifact_id = compiled.json()["artifact"]["id"]
    operation = _operation(app, project["id"], "timeline.compile")

    reverted = client.post(
        f"/api/operations/{operation['id']}/revert"
    )
    assert reverted.status_code == 200, reverted.text

    page = client.get(
        f"/api/projects/{project['id']}/artifacts",
        params={"kind": "timeline"},
    ).json()
    assert page["items"] == []
    assert client.get(f"/api/artifacts/{artifact_id}").status_code == 404


def test_render_job_creation_is_idempotent(
    app,
    client,
    project,
):
    payload = {
        "timeline": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "tracks": [],
            "duration": 1,
        },
        "name": "预览",
    }
    headers = {"Idempotency-Key": "render-preview"}
    first = client.post(
        f"/api/projects/{project['id']}/timeline/render",
        json=payload,
        headers=headers,
    )
    second = client.post(
        f"/api/projects/{project['id']}/timeline/render",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    operation = _operation(app, project["id"], "job.create")
    assert operation["affected_entities"] == [
        {"type": "job", "id": first.json()["id"]}
    ]
