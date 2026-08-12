import pytest

from app.application.agent.command_tools import HANDLERS
from app.application.agent.durable_steps import ensure_tool_step
from app.application.agent.tools import ToolContext
from app.store import UnitOfWork
from app.store.repositories import ConflictError


def _turn(app, client, project):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "耐久工具调用"},
    ).json()
    with UnitOfWork(app.state.database) as uow:
        user_message = uow.conversations.add_message(
            conversation["id"],
            "user",
            "写入一个稿件",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user_message["id"],
        )
    return turn


def _execute_write(app, project_id: str, turn_id: str, step_id: str, args):
    with UnitOfWork(app.state.database) as uow:
        context = ToolContext(
            uow,
            project_id,
            None,
            turn_id,
            app.state.settings,
            job_engine=object(),
        )
        context.step_id = step_id
        return HANDLERS["write_artifact"](context, args)


def test_durable_tool_step_replays_committed_command_after_crash(
    app,
    client,
    project,
):
    turn = _turn(app, client, project)
    arguments = {
        "kind": "generated",
        "name": "恢复稿件",
        "payload": {"body": "只应创建一次"},
    }
    with UnitOfWork(app.state.database) as uow:
        step = ensure_tool_step(
            uow,
            turn_id=turn["id"],
            logical_call_id="round-0:call-0",
            tool_name="write_artifact",
            arguments=arguments,
            request_id="request-before-crash",
        )

    first = _execute_write(
        app,
        project["id"],
        turn["id"],
        step["id"],
        arguments,
    )
    # Simulate a process death after CommandBus committed but before
    # AgentStep.finish_step and RuntimeTask checkpoint were persisted.

    with UnitOfWork(app.state.database) as uow:
        recovered_step = ensure_tool_step(
            uow,
            turn_id=turn["id"],
            logical_call_id="round-0:call-0",
            tool_name="write_artifact",
            arguments=arguments,
            request_id="request-after-restart",
        )
    assert recovered_step["id"] == step["id"]
    assert recovered_step["status"] == "running"

    replay = _execute_write(
        app,
        project["id"],
        turn["id"],
        recovered_step["id"],
        arguments,
    )
    assert replay["artifact_id"] == first["artifact_id"]
    assert replay["operation_id"] == first["operation_id"]

    with UnitOfWork(app.state.database) as uow:
        artifacts = uow.artifacts.list(project["id"])
        operations = uow.operations.list(
            project_id=project["id"],
            operation_type="artifact.create",
            limit=20,
        )
        uow.agent_turns.finish_step(
            step["id"],
            "ok",
            result=replay,
            summary="恢复后重放完成",
        )
    matching = [
        artifact for artifact in artifacts
        if artifact["name"] == "恢复稿件"
    ]
    assert len(matching) == 1
    assert len(operations) == 1

    with UnitOfWork(app.state.database) as uow:
        finished = ensure_tool_step(
            uow,
            turn_id=turn["id"],
            logical_call_id="round-0:call-0",
            tool_name="write_artifact",
            arguments=arguments,
        )
    assert finished["status"] == "ok"
    assert finished["result"]["artifact_id"] == first["artifact_id"]


def test_durable_tool_step_rejects_changed_recovery_intent(
    app,
    client,
    project,
):
    turn = _turn(app, client, project)
    with UnitOfWork(app.state.database) as uow:
        ensure_tool_step(
            uow,
            turn_id=turn["id"],
            logical_call_id="same-logical-call",
            tool_name="write_artifact",
            arguments={"payload": {"body": "original"}},
        )

    with UnitOfWork(app.state.database) as uow:
        with pytest.raises(
            ConflictError,
            match="changed during recovery",
        ):
            ensure_tool_step(
                uow,
                turn_id=turn["id"],
                logical_call_id="same-logical-call",
                tool_name="write_artifact",
                arguments={"payload": {"body": "different"}},
            )
