from app.application.agent import ToolContext, execute_tool
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


def _asset(client, project_id: str, name: str):
    response = client.post(
        f"/api/projects/{project_id}/assets",
        json={
            "kind": "reference",
            "name": name,
            "uri": f"{project_id}/{name}.png",
            "mime_type": "image/png",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _conversation(client, project_id: str):
    response = client.post(
        f"/api/projects/{project_id}/conversations",
        json={"title": "精确输入测试"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _turn(client, conversation_id: str, refs: list[dict]):
    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={
            "content": "请基于明确引用生成一张图",
            "context_refs": refs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["turn_id"]


def test_agent_generate_job_resolves_turn_and_pinned_refs(
    client,
    project,
):
    turn_artifact = _artifact(
        client,
        project["id"],
        "回合稿件",
    )
    pinned_artifact = _artifact(
        client,
        project["id"],
        "钉住稿件",
    )
    turn_asset = _asset(client, project["id"], "回合素材")
    pinned_asset = _asset(client, project["id"], "钉住素材")

    detail = client.get(
        f"/api/projects/{project['id']}"
    ).json()
    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={
            "expected_revision": detail["revision"],
            "patch": {
                "settings": {
                    **detail["settings"],
                    "pinned_refs": [
                        {
                            "type": "artifact",
                            "id": pinned_artifact["id"],
                        },
                        {
                            "type": "asset",
                            "id": pinned_asset["id"],
                        },
                    ],
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text

    conversation = _conversation(client, project["id"])
    turn_id = _turn(
        client,
        conversation["id"],
        [
            {"type": "artifact", "id": turn_artifact["id"]},
            {"type": "asset", "id": turn_asset["id"]},
            # Unit references are useful prompt context but deliberately do
            # not expand into hidden graph dependencies.
            {"type": "unit", "id": "not-expanded"},
        ],
    )

    with UnitOfWork(client.app.state.database) as uow:
        result = execute_tool(
            "generate_media",
            {
                "capability": "image",
                "prompt": "角色站在雨夜街头",
                "parameters": {"width": 1024},
                "name": "精确输入生成",
            },
            ToolContext(
                project_id=project["id"],
                unit_id=None,
                uow=uow,
            ),
            turn_id=turn_id,
            step_id="explicit-input-step",
        )
    assert result.ok, result.error
    job_id = result.created_entities[0]["id"]

    with UnitOfWork(client.app.state.database) as uow:
        job = uow.jobs.get(job_id)
    assert job["payload"]["input_version_ids"] == [
        turn_artifact["current_version"]["id"],
        pinned_artifact["current_version"]["id"],
    ]
    assert job["payload"]["input_asset_ids"] == [
        turn_asset["id"],
        pinned_asset["id"],
    ]


def test_agent_generate_job_replays_same_exact_inputs(
    client,
    project,
):
    artifact = _artifact(client, project["id"], "幂等稿件")
    asset = _asset(client, project["id"], "幂等素材")
    conversation = _conversation(client, project["id"])
    turn_id = _turn(
        client,
        conversation["id"],
        [
            {"type": "artifact", "id": artifact["id"]},
            {"type": "asset", "id": asset["id"]},
        ],
    )
    arguments = {
        "capability": "image",
        "prompt": "同一个请求",
        "parameters": {},
    }

    with UnitOfWork(client.app.state.database) as uow:
        first = execute_tool(
            "generate_media",
            arguments,
            ToolContext(project["id"], None, uow),
            turn_id=turn_id,
            step_id="same-step",
        )
    with UnitOfWork(client.app.state.database) as uow:
        second = execute_tool(
            "generate_media",
            arguments,
            ToolContext(project["id"], None, uow),
            turn_id=turn_id,
            step_id="same-step",
        )
    assert first.ok and second.ok
    assert second.created_entities == first.created_entities

    job_id = first.created_entities[0]["id"]
    with UnitOfWork(client.app.state.database) as uow:
        matching = [
            job
            for job in uow.jobs.list(project["id"])
            if job["id"] == job_id
        ]
        job = uow.jobs.get(job_id)
    assert len(matching) == 1
    assert job["payload"]["input_version_ids"] == [
        artifact["current_version"]["id"]
    ]
    assert job["payload"]["input_asset_ids"] == [asset["id"]]


def test_agent_generate_job_rejects_foreign_explicit_ref(
    client,
    project,
):
    other = client.post(
        "/api/projects",
        json={"title": "其他项目"},
    ).json()
    foreign = _artifact(client, other["id"], "外部稿件")
    conversation = _conversation(client, project["id"])
    turn_id = _turn(
        client,
        conversation["id"],
        [{"type": "artifact", "id": foreign["id"]}],
    )

    with UnitOfWork(client.app.state.database) as uow:
        result = execute_tool(
            "generate_media",
            {
                "capability": "image",
                "prompt": "不允许跨项目",
                "parameters": {},
            },
            ToolContext(project["id"], None, uow),
            turn_id=turn_id,
            step_id="foreign-ref-step",
        )
    assert not result.ok
    assert foreign["id"] in result.error
    with UnitOfWork(client.app.state.database) as uow:
        jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if job.get("turn_id") == turn_id
        ]
    assert jobs == []
