import threading

import pytest

from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
    run_durable_agent_turn,
)
from app.application.runtime_governance import (
    GovernedTaskRuntime,
    PolicyApprovalRequired,
    bind_runtime_execution,
    reset_runtime_execution,
)
from app.application.task_runtime_engine import TaskExecutionContext
from app.integrations.llm.base import ChatChunk, ToolCall
from app.store import UnitOfWork


class ScriptedAdapter:
    supports_native_tools = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        yield from response


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def cancel(self, _job_id: str) -> None:
        return


def _context(runtime, claim):
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        30,
        threading.Event(),
    )


def test_agent_generate_media_waits_for_approval_then_executes_once(
    app,
    client,
    project,
):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "高风险确认"},
    ).json()
    with UnitOfWork(app.state.database) as uow:
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "生成一张概念图",
        )
        turn = uow.agent_turns.create(conversation["id"], project["id"])
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user["id"],
        )

    runtime = GovernedTaskRuntime(app.state.database)
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
                "max_attempts": 3,
            }
        ],
    )
    adapter = ScriptedAdapter(
        [
            [
                ChatChunk(
                    kind="tool_call",
                    tool_call=ToolCall(
                        id="media-provider-call",
                        name="generate_media",
                        arguments={
                            "kind": "image",
                            "prompt": "雨夜城市概念图",
                            "params": {"width": 1024},
                        },
                    ),
                ),
                ChatChunk(
                    kind="usage",
                    usage={"prompt_tokens": 8, "completion_tokens": 3},
                ),
            ],
            [
                ChatChunk(kind="token", text="任务已创建。"),
                ChatChunk(
                    kind="usage",
                    usage={"prompt_tokens": 5, "completion_tokens": 2},
                ),
            ],
        ]
    )
    engine = RecordingJobEngine()
    first_claim = runtime.claim_next(
        "agent-policy-worker",
        kinds={AGENT_PLAN_KIND},
    )
    assert first_claim is not None
    first_context = _context(runtime, first_claim)
    token = bind_runtime_execution(first_context, turn_id=turn["id"])
    try:
        with pytest.raises(PolicyApprovalRequired) as approval:
            run_durable_agent_turn(
                app.state.database,
                app.state.settings,
                engine,
                first_context,
                adapter=adapter,
            )
    finally:
        reset_runtime_execution(token)

    assert engine.submitted == []
    with UnitOfWork(app.state.database) as uow:
        jobs_before = uow.jobs.list(project["id"])
        uow.task_runtime.resolve_policy_decision(
            approval.value.decision["id"],
            approved=True,
            decided_by_type="user",
            decided_by_id="test-user",
        )
    assert jobs_before == []

    second_claim = runtime.claim_next(
        "agent-policy-worker-2",
        kinds={AGENT_PLAN_KIND},
    )
    assert second_claim is not None
    second_context = _context(runtime, second_claim)
    token = bind_runtime_execution(second_context, turn_id=turn["id"])
    try:
        result = run_durable_agent_turn(
            app.state.database,
            app.state.settings,
            engine,
            second_context,
            adapter=adapter,
        )
    finally:
        reset_runtime_execution(token)
    runtime.complete(
        second_claim,
        result=result,
        checkpoint=second_context.checkpoint,
        usage=second_context.usage,
    )

    with UnitOfWork(app.state.database) as uow:
        jobs = uow.jobs.list(project["id"])
        decisions = uow.task_runtime.list_policy_decisions(plan["id"])
        budget = uow.task_runtime.budget_state(plan["id"])
    assert len(jobs) == 1
    assert engine.submitted == [jobs[0]["id"]]
    assert decisions[0]["status"] == "approved"
    assert budget["usage"]["tool_calls"] == 1
    assert runtime.get_plan(plan["id"])["status"] == "succeeded"
    assert adapter.calls == 2
