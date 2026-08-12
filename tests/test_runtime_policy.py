import threading
import time

import pytest

from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.runtime_governance import GovernedTaskRuntime
from app.application.task_runtime import TaskRuntime
from app.store import UnitOfWork
from app.store.repositories import ConflictError


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def cancel(self, _job_id: str) -> None:
        return


class RecordingExecutor:
    def __init__(self):
        self.notifications = 0

    def notify(self) -> None:
        self.notifications += 1


def _plan(app, project_id: str, *, key: str):
    return TaskRuntime(app.state.database).create_plan(
        project_id=project_id,
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "max_attempts": 3,
                "timeout_seconds": 900,
            }
        ],
    )


def _authorize(uow, plan, claim, action_key: str):
    return uow.task_runtime.authorize_action(
        plan_id=plan["id"],
        task_id=claim["task"]["id"],
        attempt_id=claim["attempt"]["id"],
        claim_token=claim["claim_token"],
        action_key=action_key,
        action_type="generate_media",
        risk_level="high",
        context={"turn_id": plan["subject_id"], "arguments": {}},
        checkpoint={"phase": "tools"},
        usage={"prompt_tokens": 3, "completion_tokens": 1},
    )


def test_policy_suspends_attempt_and_approval_requeues_without_double_budget(
    app,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(app, project["id"], key="policy-approval")
    assert plan["policy"]["confirmation_risk_levels"] == ["high"]
    assert plan["budget"]["max_tool_calls"] == 12
    claim = runtime.claim_next("policy-worker", kinds={AGENT_PLAN_KIND})
    assert claim is not None

    with UnitOfWork(app.state.database) as uow:
        authorization = _authorize(
            uow,
            plan,
            claim,
            "stable-high-risk-action",
        )
    decision = authorization["decision"]
    assert decision["status"] == "pending"
    stored = runtime.get_plan(plan["id"])
    assert stored["status"] == "running"
    assert stored["tasks"][0]["status"] == "waiting_approval"
    assert stored["tasks"][0]["attempts"][0]["status"] == "suspended"
    assert stored["tasks"][0]["max_attempts"] == 4

    with UnitOfWork(app.state.database) as uow:
        resolved = uow.task_runtime.resolve_policy_decision(
            decision["id"],
            approved=True,
            decided_by_type="user",
            decided_by_id="tester",
        )
    assert resolved["decision"]["status"] == "approved"
    assert resolved["plan"]["status"] == "queued"

    resumed = runtime.claim_next("policy-worker-2", kinds={AGENT_PLAN_KIND})
    assert resumed is not None
    with UnitOfWork(app.state.database) as uow:
        first = _authorize(
            uow,
            plan,
            resumed,
            "stable-high-risk-action",
        )
        replay = _authorize(
            uow,
            plan,
            resumed,
            "stable-high-risk-action",
        )
        budget = uow.task_runtime.budget_state(plan["id"])
    assert first["decision"]["status"] == "approved"
    assert first["budget_state"]["deduplicated"] is False
    assert replay["budget_state"]["deduplicated"] is True
    assert budget["usage"]["tool_calls"] == 1
    runtime.complete(resumed, result={"ok": True})


def test_cancel_expires_pending_policy_decision(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(app, project["id"], key="policy-cancel")
    claim = runtime.claim_next("policy-cancel-worker", kinds={AGENT_PLAN_KIND})
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        authorization = _authorize(
            uow,
            plan,
            claim,
            "cancel-pending-action",
        )
    runtime.cancel(plan["id"], reason="user canceled")
    with UnitOfWork(app.state.database) as uow:
        decision = uow.task_runtime.get_policy_decision(
            authorization["decision"]["id"]
        )
    assert decision["status"] == "expired"


def test_policy_authorization_rejects_stale_attempt_without_consumption(
    app,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(app, project["id"], key="stale-policy-claim")
    now = time.time() + 1
    old = runtime.claim_next(
        "stale-policy-old",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=2,
        now=now,
    )
    assert old is not None
    assert runtime.recover(kinds={AGENT_PLAN_KIND}, now=now + 3) == 1
    current = runtime.claim_next(
        "stale-policy-new",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=10,
        now=now + 4,
    )
    assert current is not None

    with pytest.raises(ConflictError, match="authorization lost"):
        with UnitOfWork(app.state.database) as uow:
            _authorize(uow, plan, old, "stale-action")
    with UnitOfWork(app.state.database) as uow:
        decisions = uow.task_runtime.list_policy_decisions(plan["id"])
        budget = uow.task_runtime.budget_state(plan["id"])
    assert decisions == []
    assert budget["usage"]["tool_calls"] == 0
    runtime.cancel(plan["id"], reason="cleanup")


def test_policy_decision_api_requeues_and_wakes_executor(
    app,
    client,
    project,
):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "确认接口"},
    ).json()
    with UnitOfWork(app.state.database) as uow:
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "需要确认",
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
            }
        ],
    )
    claim = runtime.claim_next("approval-api-worker", kinds={AGENT_PLAN_KIND})
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        authorization = _authorize(uow, plan, claim, "approval-api-action")
    decision = authorization["decision"]

    app.state.job_engine = RecordingJobEngine()
    executor = RecordingExecutor()
    app.state.agent_turn_executor = executor
    listed = client.get(
        f"/api/turns/{turn['id']}/policy-decisions",
        params={"status": "pending"},
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [decision["id"]]

    approved = client.post(
        f"/api/runtime-policy-decisions/{decision['id']}/approve",
        json={"note": "允许本次生成"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decision_note"] == "允许本次生成"
    assert executor.notifications == 1
    stored = runtime.get_plan(plan["id"])
    assert stored["status"] == "queued"
    assert stored["tasks"][0]["status"] == "queued"
