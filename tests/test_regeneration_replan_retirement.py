def test_replan_atomically_retires_draft_source(client, project):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "generated",
            "name": "重新规划根节点",
            "payload": {"body": "当前版本"},
        },
    ).json()
    created = client.post(
        f"/api/projects/{project['id']}/artifact-regeneration/plans",
        json={
            "artifact_ids": [artifact["id"]],
            "include_downstream": True,
            "client_token": "draft-source",
        },
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["status"] == "draft"

    replanned = client.post(
        f"/api/artifact-regeneration/plans/{source['id']}/replan",
        json={
            "expected_source_status": "draft",
            "expected_execution_attempt": 0,
            "reason": "重新读取当前依赖图",
            "client_token": "retire-draft",
        },
    )
    assert replanned.status_code == 201, replanned.text
    target = replanned.json()
    assert target["id"] != source["id"]
    assert target["status"] == "draft"

    retired = client.get(
        f"/api/artifact-regeneration/plans/{source['id']}"
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "canceled"

    # The old intent can no longer race the replacement by starting later.
    start_old = client.post(
        f"/api/artifact-regeneration/plans/{source['id']}/start"
    )
    assert start_old.status_code == 409, start_old.text
