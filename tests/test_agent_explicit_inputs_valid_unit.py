from app.application.agent import ToolContext, execute_tool
from app.store import UnitOfWork


def test_agent_unit_context_ref_does_not_expand_hidden_inputs(
    client,
    project,
):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "只作为上下文的单元"}]},
    ).json()[0]
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "单元引用不展开"},
    ).json()
    started = client.post(
        f"/api/conversations/{conversation['id']}/turns",
        json={
            "content": "生成图片",
            "context_refs": [{"type": "unit", "id": unit['id']}],
        },
    )
    assert started.status_code == 201, started.text
    turn_id = started.json()["turn_id"]

    with UnitOfWork(client.app.state.database) as uow:
        result = execute_tool(
            "generate_media",
            {
                "capability": "image",
                "prompt": "只使用明确实体输入",
                "parameters": {},
            },
            ToolContext(project['id'], unit['id'], uow),
            turn_id=turn_id,
            step_id="unit-context-only",
        )
    assert result.ok, result.error
    job_id = result.created_entities[0]["id"]
    with UnitOfWork(client.app.state.database) as uow:
        job = uow.jobs.get(job_id)
    assert job["payload"].get("input_version_ids") in (None, [])
    assert job["payload"].get("input_asset_ids") in (None, [])
