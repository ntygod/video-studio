from app.store import UnitOfWork


def test_artifact_api_is_idempotent_and_audited(client, project):
    body = {"kind": "custom_note", "name": "幂等稿件", "payload": {"body": "only once"}}
    headers = {"Idempotency-Key": "artifact-create-once"}
    first = client.post(f"/api/projects/{project['id']}/artifacts", json=body, headers=headers)
    second = client.post(f"/api/projects/{project['id']}/artifacts", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    page = client.get(f"/api/projects/{project['id']}/artifacts", params={"kind": "custom_note", "limit": 100}).json()
    assert [item["id"] for item in page["items"]] == [first.json()["id"]]
    operations = client.get(f"/api/projects/{project['id']}/operations").json()
    matching = [item for item in operations if item["idempotency_key"] == "artifact-create-once"]
    assert len(matching) == 1
    operation = matching[0]
    assert operation["status"] == "succeeded"
    assert operation["operation_type"] == "artifact.create"
    assert operation["result"] == {"artifact_id": first.json()["id"]}
    assert operation["arguments"]["payload_sha256"]
    assert "payload" not in operation["arguments"]


def test_failed_schema_command_is_persisted(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/artifacts",
        headers={"Idempotency-Key": "bad-timeline"},
        json={"kind": "timeline", "name": "坏时间线", "payload": {"width": 1}},
    )
    assert response.status_code == 422
    operations = client.get(f"/api/projects/{project['id']}/operations", params={"status": "failed"}).json()
    operation = next(item for item in operations if item["idempotency_key"] == "bad-timeline")
    assert operation["operation_type"] == "artifact.create"
    assert operation["status"] == "failed"
    assert "timeline payload" in operation["error"]


def test_version_precondition_conflict_is_audited(client, project):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"kind": "custom_note", "name": "版本冲突", "payload": {"body": "v1"}},
    ).json()
    response = client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        headers={"Idempotency-Key": "wrong-version"},
        json={"payload": {"body": "v2"}, "expected_current_version_id": "not-current"},
    )
    assert response.status_code == 409
    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key("wrong-version")
        versions = uow.artifacts.versions(artifact["id"])
    assert operation["status"] == "failed"
    assert "current version changed" in operation["error"]
    assert len(versions) == 1


def test_reusing_key_for_different_command_is_rejected(client, project):
    headers = {"Idempotency-Key": "same-key"}
    first = client.post(
        f"/api/projects/{project['id']}/artifacts",
        headers=headers,
        json={"kind": "custom_note", "name": "A", "payload": {"body": "a"}},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/projects/{project['id']}/artifacts",
        headers=headers,
        json={"kind": "custom_note", "name": "B", "payload": {"body": "b"}},
    )
    assert second.status_code == 409
    assert "Idempotency-Key" in second.json()["detail"]


def test_idempotency_key_length_is_bounded(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/artifacts",
        headers={"Idempotency-Key": "x" * 201},
        json={"kind": "custom_note", "name": "too long", "payload": {"body": "x"}},
    )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]
