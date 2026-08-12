import threading

import pytest

from app.application.agent.durable_loop import AGENT_PLAN_KIND, AGENT_TASK_TYPE
from app.application.runtime_governance import (
    GovernedTaskRuntime,
    RuntimeBudgetExceeded,
    bind_runtime_execution,
    reset_runtime_execution,
)
from app.application.task_runtime import TaskRuntime
from app.application.task_runtime_engine import TaskExecutionContext
from app.store import UnitOfWork


def _context(runtime, claim):
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        30,
        threading.Event(),
    )


def _agent_plan(app, project_id: str, *, key: str, budget):
    return TaskRuntime(app.state.database).create_plan(
        project_id=project_id,
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        budget=budget,
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "max_attempts": 3,
                "timeout_seconds": 900,
            }
        ],
    )


def test_budget_usage_commits_before_exception_and_event_is_deduplicated(
    app,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = TaskRuntime(app.state.database).create_plan(
        project_id=project["id"],
        kind="test.budget",
        subject_type="test",
        subject_id="token-budget",
        idempotency_key="token-budget",
        budget={"max_prompt_tokens": 5},
        tasks=[{"key": "execute", "type": "test.execute"}],
    )
    claim = runtime.claim_next("budget-worker", kinds={"test.budget"})
    assert claim is not None
    context = _context(runtime, claim)
    token = bind_runtime_execution(context, turn_id="budget-test")
    try:
        runtime.heartbeat(
            claim,
            usage={"prompt_tokens": 5, "completion_tokens": 0},
        )
        with pytest.raises(RuntimeBudgetExceeded) as exceeded:
            runtime.heartbeat(
                claim,
                usage={"prompt_tokens": 6, "completion_tokens": 0},
            )
        with pytest.raises(RuntimeBudgetExceeded):
            runtime.heartbeat(
                claim,
                usage={"prompt_tokens": 6, "completion_tokens": 0},
            )
    finally:
        reset_runtime_execution(token)
    assert exceeded.value.violation["dimension"] == "max_prompt_tokens"
    with UnitOfWork(app.state.database) as uow:
        state = uow.task_runtime.budget_state(plan["id"])
    assert state["usage"]["prompt_tokens"] == 6
    assert state["violation"]["dimension"] == "max_prompt_tokens"
    events = [
        event
        for event in runtime.events(plan["id"])
        if event["event_type"] == "agent.budget.exceeded"
    ]
    assert len(events) == 1
    runtime.fail(claim, error="budget exceeded", retryable=False)


def test_agent_wall_budget_is_checked_after_claim(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _agent_plan(
        app,
        project["id"],
        key="agent-wall-budget",
        budget={"max_wall_seconds": 1},
    )
    claim = runtime.claim_next(
        "agent-wall-worker",
        kinds={AGENT_PLAN_KIND},
        now=100,
    )
    assert claim is not None
    context = _context(runtime, claim)
    token = bind_runtime_execution(context, turn_id="agent-wall-budget")
    try:
        with pytest.raises(RuntimeBudgetExceeded) as exceeded:
            runtime.heartbeat(claim, now=102)
    finally:
        reset_runtime_execution(token)
    assert exceeded.value.violation["dimension"] == "max_wall_seconds"
    runtime.fail(claim, error="wall budget exceeded", retryable=False)
    assert runtime.get_plan(plan["id"])["status"] == "failed"


def test_generic_wall_budget_can_fail_before_claim(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = TaskRuntime(app.state.database).create_plan(
        project_id=project["id"],
        kind="test.wall-budget",
        subject_type="test",
        subject_id="wall-budget",
        idempotency_key="wall-budget",
        budget={"max_wall_seconds": 1},
        tasks=[{"key": "execute", "type": "test.execute"}],
    )
    assert runtime.claim_next(
        "late-worker",
        kinds={"test.wall-budget"},
        now=plan["created_at"] + 5,
    ) is None
    failed = runtime.get_plan(plan["id"])
    assert failed["status"] == "failed"
    assert failed["tasks"][0]["attempts"] == []
    assert "max_wall_seconds" in failed["tasks"][0]["error"]
