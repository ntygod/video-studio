from app.application.agent.tools import TOOL_BY_NAME, ToolContext
from app.store import UnitOfWork


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


def _tool_context(
    app,
    project_id: str,
    turn_id: str,
    job_engine=None,
):
    return ToolContext(
        None,
        project_id,
        None,
        turn_id,
        app.state.settings,
        job_engine or RecordingJobEngine(),
    )


def _create_turn_and_step(
    app,
    project_id: str,
    tool_name: str,
):
    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(
            project_id,
            None,
            "Agent command test",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project_id,
        )
        step = uow.agent_turns.add_step(
            turn["id"],
            "tool",
            tool_name=tool_name,
            arguments={},
            request_id="test-request",
        )
    return turn, step


def _invoke(
    app,
    project_id: str,
    turn_id: str,
    tool_name: str,
    args: dict,
    job_engine=None,
):
    with UnitOfWork(app.state.database) as uow:
        ctx = ToolContext(
            uow,
            project_id,
            None,
            turn_id,
            app.state.settings,
            job_engine or RecordingJobEngine(),
        )
        return TOOL_BY_NAME[tool_name].handler(ctx, args)


def test_agent_artifact_write_uses_idempotent_command(
    app,
    client,
    project,
):
    turn, step = _create_turn_and_step(
        app,
        project["id"],
        "write_artifact",
    )
    args = {
        "kind": "custom_note",
        "name": "Agent 稿件",
        "payload": {"body": "only once"},
    }

    first = _invoke(
        app,
        project["id"],
        turn["id"],
        "write_artifact",
        args,
    )
    second = _invoke(
        app,
        project["id"],
        turn["id"],
        "write_artifact",
        args,
    )
    assert second["artifact_id"] == first["artifact_id"]
    assert second["operation_id"] == first["operation_id"]

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.get(
            first["operation_id"]
        )
        artifacts = uow.artifacts.list(
            project["id"],
            include_payload=False,
        )
    matching = [
        item
        for item in artifacts
        if item["name"] == "Agent 稿件"
    ]
    assert len(matching) == 1
    assert operation["actor_type"] == "agent"
    assert operation["turn_id"] == turn["id"]
    assert operation["idempotency_key"] == (
        f"agent:{turn['id']}:{step['id']}"
    )


def test_agent_create_units_and_proposal_use_commands(
    app,
    project,
):
    turn, _ = _create_turn_and_step(
        app,
        project["id"],
        "create_units",
    )
    units = _invoke(
        app,
        project["id"],
        turn["id"],
        "create_units",
        {"units": [{"title": "第一章"}]},
    )
    assert len(units["units"]) == 1

    with UnitOfWork(app.state.database) as uow:
        uow.agent_turns.finish_step(
            uow.agent_turns.steps(turn["id"])[-1]["id"],
            "ok",
        )
        step = uow.agent_turns.add_step(
            turn["id"],
            "tool",
            tool_name="propose_restructure",
            arguments={},
        )
    proposal = _invoke(
        app,
        project["id"],
        turn["id"],
        "propose_restructure",
        {
            "title": "改名建议",
            "changes": [
                {
                    "action": "rename",
                    "unit_id": units["units"][0]["id"],
                    "title": "新的第一章",
                }
            ],
        },
    )

    with UnitOfWork(app.state.database) as uow:
        stored = uow.proposals.get(
            proposal["proposal_id"]
        )
        operation = uow.operations.get(
            proposal["operation_id"]
        )
    assert stored["status"] == "pending"
    assert stored["artifact_kind"] == "structure"
    assert operation["actor_type"] == "agent"
    assert operation["idempotency_key"] == (
        f"agent:{turn['id']}:{step['id']}"
    )


def test_agent_media_generation_creates_audited_job(
    app,
    project,
):
    turn, _ = _create_turn_and_step(
        app,
        project["id"],
        "generate_media",
    )
    engine = RecordingJobEngine()
    result = _invoke(
        app,
        project["id"],
        turn["id"],
        "generate_media",
        {
            "kind": "image",
            "prompt": "一座雨中的城市",
            "params": {},
        },
        job_engine=engine,
    )

    assert engine.submitted == [result["job_id"]]
    with UnitOfWork(app.state.database) as uow:
        job = uow.jobs.get(result["job_id"])
        operation = uow.operations.get(
            result["operation_id"]
        )
    assert job["turn_id"] == turn["id"]
    assert job["payload"]["capability"] == "image"
    assert operation["operation_type"] == "job.create"
    assert operation["actor_type"] == "agent"
