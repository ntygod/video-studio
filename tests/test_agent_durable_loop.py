import threading
import time

from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
    run_durable_agent_turn,
)
from app.application.task_runtime import TaskRuntime
from app.application.task_runtime_engine import TaskExecutionContext
from app.integrations.llm.base import ChatChunk, ToolCall
from app.store import UnitOfWork


class SimulatedProcessCrash(BaseException):
    pass


class ScriptedAdapter:
    supports_native_tools = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        yield from response


def _turn(app, client, project):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "耐久 Agent"},
    ).json()
    with UnitOfWork(app.state.database) as uow:
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "创建一份稿件，然后告诉我已完成。",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user["id"],
        )
    return conversation, turn


def _context(runtime, claim, lease_seconds=5):
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        lease_seconds,
        threading.Event(),
    )


def test_agent_tool_loop_recovers_command_checkpoint_crash_without_duplicates(
    app,
    client,
    project,
):
    conversation, turn = _turn(app, client, project)
    runtime = TaskRuntime(app.state.database)
    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="agent_turn",
        subject_id=turn["id"],
        idempotency_key=f"agent-turn:{turn['id']}",
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "payload": {"turn_id": turn["id"]},
                "max_attempts": 2,
            }
        ],
    )
    arguments = {
        "kind": "generated",
        "name": "耐久稿件",
        "payload": {"body": "exactly once"},
    }
    adapter = ScriptedAdapter(
        [
            [
                ChatChunk(
                    kind="tool_call",
                    tool_call=ToolCall(
                        id="provider-call-1",
                        name="write_artifact",
                        arguments=arguments,
                    ),
                ),
                ChatChunk(
                    kind="usage",
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                    },
                ),
            ],
            [
                ChatChunk(kind="token", text="已经完成。"),
                ChatChunk(
                    kind="usage",
                    usage={
                        "prompt_tokens": 8,
                        "completion_tokens": 3,
                    },
                ),
            ],
        ]
    )
    now = time.time() + 1
    first_claim = runtime.claim_next(
        "agent-old",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=5,
        now=now,
    )
    assert first_claim is not None
    first_context = _context(runtime, first_claim)
    crashed = {"done": False}

    def crash_after_command(point, payload):
        if point == "after_tool_command" and not crashed["done"]:
            crashed["done"] = True
            assert payload["ok"] is True
            raise SimulatedProcessCrash()

    try:
        run_durable_agent_turn(
            app.state.database,
            app.state.settings,
            job_engine=object(),
            context=first_context,
            adapter=adapter,
            fault_hook=crash_after_command,
        )
        raise AssertionError("simulated crash did not occur")
    except SimulatedProcessCrash:
        pass

    with UnitOfWork(app.state.database) as uow:
        after_crash = uow.agent_turns.get(turn["id"])
        artifacts = [
            item
            for item in uow.artifacts.list(project["id"])
            if item["name"] == "耐久稿件"
        ]
        operations = [
            item
            for item in uow.operations.list(
                project_id=project["id"],
                limit=50,
            )
            if item["operation_type"] == "artifact.create"
        ]
    assert after_crash["status"] == "running"
    assert after_crash["steps"][0]["status"] == "running"
    assert len(artifacts) == 1
    assert len(operations) == 1

    assert runtime.recover(
        kinds={AGENT_PLAN_KIND},
        now=now + 10,
    ) == 1
    second_claim = runtime.claim_next(
        "agent-new",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=5,
        now=now + 11,
    )
    assert second_claim is not None
    second_context = _context(runtime, second_claim)
    result = run_durable_agent_turn(
        app.state.database,
        app.state.settings,
        job_engine=object(),
        context=second_context,
        adapter=adapter,
    )
    runtime.complete(
        second_claim,
        result=result,
        checkpoint=second_context.checkpoint,
        usage=second_context.usage,
        now=now + 12,
    )

    assert adapter.calls == 2
    completed = runtime.get_plan(plan["id"])
    assert completed["status"] == "succeeded"
    assert [
        attempt["status"]
        for attempt in completed["tasks"][0]["attempts"]
    ] == ["interrupted", "succeeded"]

    with UnitOfWork(app.state.database) as uow:
        finished = uow.agent_turns.get(turn["id"])
        messages = uow.conversations.list_messages(conversation["id"])
        artifacts = [
            item
            for item in uow.artifacts.list(project["id"])
            if item["name"] == "耐久稿件"
        ]
        operations = [
            item
            for item in uow.operations.list(
                project_id=project["id"],
                limit=50,
            )
            if item["operation_type"] == "artifact.create"
        ]
    assert finished["status"] == "succeeded"
    assert finished["prompt_tokens"] == 18
    assert finished["completion_tokens"] == 7
    assert len(finished["steps"]) == 1
    assert finished["steps"][0]["status"] == "ok"
    assert len(artifacts) == 1
    assert len(operations) == 1
    assistant_messages = [
        message for message in messages if message["role"] == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "已经完成。"

    event_types = [
        event["event_type"] for event in runtime.events(plan["id"])
    ]
    assert "agent.step.done" in event_types
    assert "agent.message" in event_types
    assert "agent.done" in event_types


def test_agent_finalization_replays_existing_assistant_message(
    app,
    client,
    project,
):
    conversation, turn = _turn(app, client, project)
    runtime = TaskRuntime(app.state.database)
    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="agent_turn",
        subject_id=turn["id"],
        idempotency_key=f"agent-turn:{turn['id']}",
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "payload": {"turn_id": turn["id"]},
                "max_attempts": 2,
            }
        ],
    )
    adapter = ScriptedAdapter(
        [[ChatChunk(kind="token", text="只写一次")]]
    )
    now = time.time() + 1
    claim = runtime.claim_next(
        "agent-finalize",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=5,
        now=now,
    )
    assert claim is not None
    context = _context(runtime, claim)

    finalized = {"done": False}

    def crash_after_finalize(point, _payload):
        if point == "after_turn_finalized" and not finalized["done"]:
            finalized["done"] = True
            raise SimulatedProcessCrash()

    try:
        run_durable_agent_turn(
            app.state.database,
            app.state.settings,
            job_engine=object(),
            context=context,
            adapter=adapter,
            fault_hook=crash_after_finalize,
        )
        raise AssertionError("simulated crash did not occur")
    except SimulatedProcessCrash:
        pass

    assert runtime.recover(
        kinds={AGENT_PLAN_KIND},
        now=now + 10,
    ) == 1
    replay_claim = runtime.claim_next(
        "agent-finalize-replay",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=5,
        now=now + 11,
    )
    assert replay_claim is not None
    replay_context = _context(runtime, replay_claim)
    result = run_durable_agent_turn(
        app.state.database,
        app.state.settings,
        job_engine=object(),
        context=replay_context,
        adapter=adapter,
    )
    runtime.complete(
        replay_claim,
        result=result,
        checkpoint=replay_context.checkpoint,
        usage=replay_context.usage,
        now=now + 12,
    )

    with UnitOfWork(app.state.database) as uow:
        messages = uow.conversations.list_messages(conversation["id"])
        stored = uow.agent_turns.get(turn["id"])
    assistant_messages = [
        message for message in messages if message["role"] == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert stored["assistant_message_id"] == assistant_messages[0]["id"]
    assert adapter.calls == 1
    assert runtime.get_plan(plan["id"])["status"] == "succeeded"
