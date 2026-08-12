import pytest

from app.application.agent.tools import TOOL_BY_NAME, ToolContext
from app.store import UnitOfWork
from app.store.repositories import NotFoundError


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


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


def _create_turn_and_step(
    app,
    project_id: str,
    tool_name: str,
    refs: list[dict],
):
    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(
            project_id,
            None,
            "Agent explicit input test",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project_id,
            context_refs=refs,
        )
        step = uow.agent_turns.add_step(
            turn["id"],
            "tool",
            tool_name=tool_name,
            arguments={},
            request_id="explicit-input-test",
        )
    return turn, step


def _invoke(
    app,
    project_id: str,
    turn_id: str,
    tool_name: str,
    args: dict,
    *,
    engine=None,
):
    with UnitOfWork(app.state.database) as uow:
        context = ToolContext(
            uow,
            project_id,
            None,
            turn_id,
            app.state.settings,
            engine or RecordingJobEngine(),
        )
        return TOOL_BY_NAME[tool_name].handler(context, args)


def _set_pinned_refs(client, project_id: str, refs: list[dict]):
    detail = client.get(f"/api/projects/{project_id}").json()
    response = client.patch(
        f"/api/projects/{project_id}",
        json={
            "expected_revision": detail["revision"],
            "patch": {
                "settings": {
                    **detail["settings"],
                    "pinned_refs": refs,
                }
            },
        },
    )
    assert response.status_code == 200, response.text


def test_agent_media_job_freezes_direct_turn_and_pinned_inputs(
    app,
    client,
    project,
):
    direct_artifact = _artifact(
        client,
        project["id"],
        "工具直接指定稿件",
    )
    turn_artifact = _artifact(
        client,
        project["id"],
        "回合引用稿件",
    )
    pinned_artifact = _artifact(
        client,
        project["id"],
        "钉住稿件",
    )
    direct_asset = _asset(
        client,
        project["id"],
        "工具直接指定素材",
    )
    turn_asset = _asset(client, project["id"], "回合引用素材")
    pinned_asset = _asset(client, project["id"], "钉住素材")
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "只作为上下文的单元"}]},
    ).json()[0]

    _set_pinned_refs(
        client,
        project["id"],
        [
            {"type": "artifact", "id": pinned_artifact["id"]},
            {"type": "asset", "id": pinned_asset["id"]},
        ],
    )
    turn, _step = _create_turn_and_step(
        app,
        project["id"],
        "generate_media",
        [
            {"type": "artifact", "id": turn_artifact["id"]},
            {"type": "asset", "id": turn_asset["id"]},
            # Valid Unit context must not expand into every child entity.
            {"type": "unit", "id": unit["id"]},
        ],
    )
    engine = RecordingJobEngine()
    result = _invoke(
        app,
        project["id"],
        turn["id"],
        "generate_media",
        {
            "kind": "image",
            "prompt": "角色站在雨夜街头",
            "params": {"width": 1024},
            "input_artifact_ids": [direct_artifact["id"]],
            "input_asset_ids": [direct_asset["id"]],
        },
        engine=engine,
    )

    assert engine.submitted == [result["job_id"]]
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.get(result["job_id"])
    assert "input_artifact_ids" not in job["payload"]
    assert job["payload"]["input_version_ids"] == [
        direct_artifact["current_version"]["id"],
        turn_artifact["current_version"]["id"],
        pinned_artifact["current_version"]["id"],
    ]
    assert job["payload"]["input_asset_ids"] == [
        direct_asset["id"],
        turn_asset["id"],
        pinned_asset["id"],
    ]


def test_agent_artifact_write_registers_and_replays_exact_inputs(
    app,
    client,
    project,
):
    source = _artifact(client, project["id"], "上游稿件")
    source_version_id = source["current_version"]["id"]
    asset = _asset(client, project["id"], "角色参考图")
    turn, step = _create_turn_and_step(
        app,
        project["id"],
        "write_artifact",
        [
            {"type": "artifact", "id": source["id"]},
            {"type": "asset", "id": asset["id"]},
        ],
    )
    arguments = {
        "kind": "custom_note",
        "name": "Agent 派生稿",
        "payload": {"body": "由明确输入生成"},
    }

    first = _invoke(
        app,
        project["id"],
        turn["id"],
        "write_artifact",
        arguments,
    )
    advanced = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "上游 v2"}},
    )
    assert advanced.status_code == 201, advanced.text
    second = _invoke(
        app,
        project["id"],
        turn["id"],
        "write_artifact",
        arguments,
    )

    assert second["artifact_id"] == first["artifact_id"]
    assert second["operation_id"] == first["operation_id"]
    with UnitOfWork(app.state.database) as uow:
        artifact = uow.artifacts.get(first["artifact_id"])
        derivation = uow.artifact_graph.derivation(
            artifact["current_version_id"]
        )
        operation = uow.operations.get(first["operation_id"])
        matching = [
            item
            for item in uow.artifacts.list(
                project["id"],
                include_payload=False,
            )
            if item["name"] == "Agent 派生稿"
        ]

    assert len(matching) == 1
    assert [
        edge["upstream_version_id"]
        for edge in derivation["dependencies"]
    ] == [source_version_id]
    assert [
        edge["upstream_asset_id"]
        for edge in derivation["asset_dependencies"]
    ] == [asset["id"]]
    assert derivation["provenance"]["operation_id"] == (
        first["operation_id"]
    )
    assert derivation["provenance"]["prompt_version"] == (
        "agent-write-artifact@1"
    )
    assert operation["idempotency_key"] == (
        f"agent:{turn['id']}:{step['id']}"
    )
    # The old exact input stays frozen even after the source advanced.
    assert derivation["provenance"]["input_version_ids"] == [
        source_version_id
    ]


def test_agent_production_tool_rejects_foreign_context_ref(
    app,
    client,
    project,
):
    other = client.post(
        "/api/projects",
        json={"title": "其他项目"},
    ).json()
    foreign = _artifact(client, other["id"], "外部稿件")
    turn, _step = _create_turn_and_step(
        app,
        project["id"],
        "generate_media",
        [{"type": "artifact", "id": foreign["id"]}],
    )
    engine = RecordingJobEngine()

    with pytest.raises(NotFoundError, match=foreign["id"]):
        _invoke(
            app,
            project["id"],
            turn["id"],
            "generate_media",
            {
                "kind": "image",
                "prompt": "不允许跨项目",
                "params": {},
            },
            engine=engine,
        )

    assert engine.submitted == []
    with UnitOfWork(app.state.database) as uow:
        jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if job.get("turn_id") == turn["id"]
        ]
    assert jobs == []
