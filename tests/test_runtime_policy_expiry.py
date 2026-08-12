from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.runtime_governance import GovernedTaskRuntime
from app.application.task_runtime import TaskRuntime
from app.store import UnitOfWork


def _expiring_plan(app, project, key: str):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = TaskRuntime(app.state.database).create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="agent_turn",
        subject_id=f"turn-{key}",
        idempotency_key=key,
        policy={"approval_ttl_seconds": 1},
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "max_attempts": 3,
            }
        ],
    )
    claim = runtime.claim_next(
        f"{key}-worker",
        kinds={AGENT_PLAN_KIND},
    )
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        authorization = uow.task_runtime.authorize_action(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            action_key=f"{key}-action",
            action_type="generate_media",
            risk_level="high",
            context={"turn_id": f"turn-{key}", "arguments": {}},
            checkpoint={"phase": "tools"},
            usage={"prompt_tokens": 4, "completion_tokens": 1},
            now=100,
        )
    return runtime, plan, authorization["decision"]


def test_pending_policy_decision_expires_and_resumes_once(app, project):
    runtime, plan, decision = _expiring_plan(
        app,
        project,
        "policy-expiry",
    )
    assert decision["status"] == "pending"
    assert decision["expires_at"] == 101
    waiting = runtime.get_plan(plan["id"])
    assert waiting["tasks"][0]["status"] == "waiting_approval"

    assert runtime.recover(kinds={AGENT_PLAN_KIND}, now=102) == 1
    assert runtime.recover(kinds={AGENT_PLAN_KIND}, now=103) == 0
    with UnitOfWork(app.state.database) as uow:
        expired = uow.task_runtime.get_policy_decision(decision["id"])
    assert expired["status"] == "expired"
    assert expired["decided_by_id"] == "approval-expiry-reaper"
    resumed_plan = runtime.get_plan(plan["id"])
    assert resumed_plan["status"] == "queued"
    assert resumed_plan["tasks"][0]["status"] == "queued"

    resumed = runtime.claim_next(
        "expiry-resume-worker",
        kinds={AGENT_PLAN_KIND},
        now=104,
    )
    assert resumed is not None
    with UnitOfWork(app.state.database) as uow:
        replay = uow.task_runtime.authorize_action(
            plan_id=plan["id"],
            task_id=resumed["task"]["id"],
            attempt_id=resumed["attempt"]["id"],
            claim_token=resumed["claim_token"],
            action_key="policy-expiry-action",
            action_type="generate_media",
            risk_level="high",
            context={"turn_id": "turn-policy-expiry", "arguments": {}},
            checkpoint={"phase": "tools"},
            usage={"prompt_tokens": 4, "completion_tokens": 1},
            now=104,
        )
        budget = uow.task_runtime.budget_state(plan["id"], now=104)
    assert replay["decision"]["status"] == "expired"
    assert replay["budget_state"] is None
    assert budget["usage"]["tool_calls"] == 0

    events = runtime.events(plan["id"])
    resolved = [
        event
        for event in events
        if event["event_type"] == "agent.approval.resolved"
    ]
    assert len(resolved) == 1
    runtime.fail(
        resumed,
        error="approval expired",
        retryable=False,
        now=105,
    )


def test_late_approval_commits_expiry_before_reporting_conflict(app, project):
    _runtime, plan, decision = _expiring_plan(
        app,
        project,
        "policy-expiry-cas",
    )
    with UnitOfWork(app.state.database) as uow:
        result = uow.task_runtime.resolve_policy_decision(
            decision["id"],
            approved=True,
            decided_by_type="user",
            decided_by_id="late-reviewer",
            now=102,
        )
    assert result["decision"]["status"] == "expired"
    with UnitOfWork(app.state.database) as uow:
        expired = uow.task_runtime.get_policy_decision(decision["id"])
    assert expired["status"] == "expired"
    stored = TaskRuntime(app.state.database).get_plan(plan["id"])
    assert stored["status"] == "queued"
    assert stored["tasks"][0]["status"] == "queued"
