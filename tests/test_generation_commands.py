from app.store import UnitOfWork


def test_single_generation_job_is_idempotent(
    app,
    client,
    project,
):
    headers = {"Idempotency-Key": "generate-once"}
    body = {
        "capability": "llm",
        "prompt": "生成一句话",
        "artifact_kind": "generated",
        "artifact_name": "结果",
    }
    first = client.post(
        f"/api/projects/{project['id']}/generate",
        json=body,
        headers=headers,
    )
    second = client.post(
        f"/api/projects/{project['id']}/generate",
        json=body,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "generate-once"
        )
    assert operation["operation_type"] == "job.create"
    assert operation["affected_entities"] == [
        {"type": "job", "id": first.json()["id"]}
    ]


def test_batch_generation_job_graph_is_atomic_and_idempotent(
    app,
    client,
    project,
):
    units = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "镜头一", "summary": "晨光"},
                {"title": "镜头二", "summary": "夜色"},
            ]
        },
    ).json()
    body = {
        "unit_ids": [unit["id"] for unit in units],
        "capability": "image",
        "prompt_template": "{unit.title}:{unit.summary}",
        "params": {"size": "1024x1024"},
    }
    headers = {"Idempotency-Key": "batch-generate-once"}

    first = client.post(
        f"/api/projects/{project['id']}/generate/batch",
        json=body,
        headers=headers,
    )
    second = client.post(
        f"/api/projects/{project['id']}/generate/batch",
        json=body,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    result = first.json()
    with UnitOfWork(app.state.database) as uow:
        parent = uow.jobs.get(result["parent_job_id"])
        children = [
            uow.jobs.get(job_id)
            for job_id in result["child_job_ids"]
        ]
        operation = uow.operations.find_by_idempotency_key(
            "batch-generate-once"
        )
    assert parent["payload"]["child_count"] == 2
    assert parent["payload"]["child_job_ids"] == result["child_job_ids"]
    assert [child["parent_job_id"] for child in children] == [
        parent["id"],
        parent["id"],
    ]
    assert operation["operation_type"] == "job.batch.create"
    assert len(operation["affected_entities"]) == 3


def test_batch_generation_rejects_duplicate_units_without_jobs(
    app,
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "重复"}]},
    ).json()[0]
    response = client.post(
        f"/api/projects/{project['id']}/generate/batch",
        json={
            "unit_ids": [unit["id"], unit["id"]],
            "capability": "image",
        },
        headers={"Idempotency-Key": "duplicate-batch"},
    )
    assert response.status_code == 422
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "duplicate-batch"
        )
        jobs = uow.jobs.list(project_id=project["id"])
    assert operation["status"] == "failed"
    assert jobs == []
