from app.application.task_runtime import TaskRuntime


def test_runtime_observability_api_exposes_plan_tasks_and_events(
    app,
    client,
    project,
):
    runtime = TaskRuntime(app.state.database)
    plan = runtime.create_plan(
        project_id=project["id"],
        kind="test.observable",
        subject_type="artifact",
        subject_id="artifact-1",
        idempotency_key="observable-plan",
        tasks=[
            {
                "key": "prepare",
                "type": "test.prepare",
                "payload": {"private_input": "kept in runtime"},
            },
            {
                "key": "publish",
                "type": "test.publish",
                "depends_on": ["prepare"],
            },
        ],
    )

    listed = client.get(
        f"/api/projects/{project['id']}/runtime-plans",
        params={"kind": "test.observable"},
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [plan["id"]]
    assert "tasks" not in listed.json()[0]

    fetched = client.get(f"/api/runtime-plans/{plan['id']}")
    assert fetched.status_code == 200, fetched.text
    detail = fetched.json()
    assert detail["status"] == "queued"
    assert [task["task_key"] for task in detail["tasks"]] == [
        "prepare",
        "publish",
    ]
    assert detail["tasks"][1]["depends_on_task_ids"] == [
        detail["tasks"][0]["id"]
    ]

    task = client.get(
        f"/api/runtime-tasks/{detail['tasks'][0]['id']}"
    )
    assert task.status_code == 200, task.text
    assert task.json()["payload"]["private_input"] == (
        "kept in runtime"
    )
    assert task.json()["attempts"] == []

    first_page = client.get(
        f"/api/runtime-plans/{plan['id']}/events",
        params={"limit": 2},
    )
    assert first_page.status_code == 200, first_page.text
    first = first_page.json()
    assert [item["seq"] for item in first["items"]] == [1, 2]
    assert first["next_after_seq"] == 2

    second_page = client.get(
        f"/api/runtime-plans/{plan['id']}/events",
        params={"after_seq": first["next_after_seq"]},
    )
    assert second_page.status_code == 200, second_page.text
    second = second_page.json()
    assert second["items"]
    assert all(item["seq"] > 2 for item in second["items"])
    assert second["items"][-1]["event_type"] == "plan.queued"


def test_runtime_observability_api_respects_project_and_missing_rows(
    app,
    client,
    project,
):
    runtime = TaskRuntime(app.state.database)
    runtime.create_plan(
        project_id=project["id"],
        kind="test.filter",
        idempotency_key="filter-one",
        tasks=[{"key": "one", "type": "test.one"}],
    )

    empty = client.get(
        f"/api/projects/{project['id']}/runtime-plans",
        params={"kind": "other.kind", "status": "queued"},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json() == []

    missing_plan = client.get("/api/runtime-plans/missing")
    missing_task = client.get("/api/runtime-tasks/missing")
    assert missing_plan.status_code == 404
    assert missing_task.status_code == 404
