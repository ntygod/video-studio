from app.store import UnitOfWork


def _artifact(client, project_id: str, name: str):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": "generated",
            "name": name,
            "payload": {"body": name},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_plan_create_token_replays_one_intent_but_allows_the_next(
    client,
    project,
):
    artifact = _artifact(client, project["id"], "普通稿件")
    endpoint = (
        f"/api/projects/{project['id']}/"
        "artifact-regeneration/plans"
    )
    first_body = {
        "artifact_ids": [artifact["id"]],
        "include_downstream": True,
        "client_token": "intent-one",
    }
    first = client.post(endpoint, json=first_body)
    retry = client.post(endpoint, json=first_body)
    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]

    second = client.post(
        endpoint,
        json={**first_body, "client_token": "intent-two"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]

    listed = client.get(endpoint)
    assert listed.status_code == 200, listed.text
    assert {item["id"] for item in listed.json()} == {
        first.json()["id"],
        second.json()["id"],
    }


def test_plan_start_operation_does_not_claim_a_reversible_inverse(
    client,
    project,
):
    artifact = _artifact(client, project["id"], "无需修复")
    created = client.post(
        f"/api/projects/{project['id']}/"
        "artifact-regeneration/plans",
        json={
            "artifact_ids": [artifact["id"]],
            "client_token": "start-inverse-test",
        },
    )
    assert created.status_code == 201, created.text
    plan = created.json()

    started = client.post(
        f"/api/artifact-regeneration/plans/{plan['id']}/start"
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "succeeded"

    key = (
        f"regeneration-plan-start:{plan['id']}:"
        f"{plan['snapshot_sha256']}"
    )
    with UnitOfWork(client.app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(key)
    assert operation is not None
    assert operation["inverse_operation"] is None
