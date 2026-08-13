import threading

import pytest

from app.application.agent.runtime_cost_metering import MeteredLLMAdapter
from app.application.runtime_governance import (
    GovernedTaskRuntime,
    RuntimeBudgetExceeded,
    bind_runtime_execution,
    reset_runtime_execution,
)
from app.application.task_runtime_engine import TaskExecutionContext
from app.integrations.llm.base import ChatChunk
from app.store import UnitOfWork


class CountingAdapter:
    supports_native_tools = True
    model = "policy-model"

    def __init__(self, *, report_usage: bool):
        self.report_usage = report_usage
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        yield ChatChunk(kind="token", text="draft")
        if self.report_usage:
            yield ChatChunk(
                kind="usage",
                usage={
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "_provider_request_id": "policy-response",
                },
            )
        yield ChatChunk(kind="done")


def _context(runtime, claim):
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        30,
        threading.Event(),
    )


def _snapshot(pricing):
    return {
        "version": 1,
        "provider_profile_id": "provider-policy",
        "provider_name": "Policy Provider",
        "adapter": "openai",
        "model_profile_id": "model-profile-policy",
        "model_id": "policy-model",
        "capability_type": "llm",
        "pricing": pricing,
    }


def _plan(runtime, project_id, key, mode):
    return runtime.create_plan(
        project_id=project_id,
        kind="test.cost-policy",
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        policy={
            "provider_cost_policy": {
                "unpriced_provider_mode": mode,
            }
        },
        tasks=[{"key": "execute", "type": "test.execute"}],
    )


def test_project_cost_policy_is_audited_and_frozen_per_agent_plan(
    app,
    client,
    project,
):
    initial = client.get(
        f"/api/projects/{project['id']}/runtime-cost-policy"
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["policy"] == {
        "unpriced_provider_mode": "allow"
    }

    strict = client.patch(
        f"/api/projects/{project['id']}/runtime-cost-policy",
        json={
            "expected_revision": initial.json()["revision"],
            "unpriced_provider_mode": "block",
        },
    )
    assert strict.status_code == 200, strict.text
    assert strict.json()["policy"]["unpriced_provider_mode"] == "block"

    runtime = GovernedTaskRuntime(app.state.database)
    frozen = runtime.create_plan(
        project_id=project["id"],
        kind="agent.turn",
        subject_type="agent_turn",
        subject_id="strict-turn",
        idempotency_key="strict-agent-plan",
        tasks=[{"key": "execute", "type": "agent.turn.execute"}],
        queue=False,
    )
    assert frozen["policy"]["provider_cost_policy"] == {
        "unpriced_provider_mode": "block"
    }

    relaxed = client.patch(
        f"/api/projects/{project['id']}/runtime-cost-policy",
        json={
            "expected_revision": strict.json()["revision"],
            "unpriced_provider_mode": "allow",
        },
    )
    assert relaxed.status_code == 200, relaxed.text
    assert runtime.get_plan(frozen["id"])["policy"][
        "provider_cost_policy"
    ]["unpriced_provider_mode"] == "block"

    next_plan = runtime.create_plan(
        project_id=project["id"],
        kind="agent.turn",
        subject_type="agent_turn",
        subject_id="relaxed-turn",
        idempotency_key="relaxed-agent-plan",
        tasks=[{"key": "execute", "type": "agent.turn.execute"}],
        queue=False,
    )
    assert next_plan["policy"]["provider_cost_policy"] == {
        "unpriced_provider_mode": "allow"
    }


def test_strict_policy_blocks_unpriced_model_before_provider_call(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "strict-preflight", "block")
    claim = runtime.claim_next(
        "cost-policy-worker",
        kinds={"test.cost-policy"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    inner = CountingAdapter(report_usage=True)
    adapter = MeteredLLMAdapter(
        inner,
        pricing_snapshot=_snapshot({}),
        checkpoint={"round": 0, "cost_microunits": 0},
    )
    token = bind_runtime_execution(context, turn_id="strict-preflight")
    try:
        with pytest.raises(RuntimeBudgetExceeded) as blocked:
            list(adapter.stream([], []))
    finally:
        reset_runtime_execution(token)

    assert blocked.value.violation["dimension"] == "unpriced_provider"
    assert blocked.value.violation["phase"] == "preflight"
    assert inner.calls == 0
    with UnitOfWork(app.state.database) as uow:
        assert uow.task_runtime.list_cost_entries(plan["id"]) == []
        events = uow.task_runtime.list_events(plan["id"])
    assert [event["event_type"] for event in events].count(
        "runtime.cost_policy.blocked"
    ) == 1
    runtime.fail(claim, error="strict cost policy", retryable=False)


def test_strict_policy_audits_missing_usage_then_fails(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "strict-post-usage", "block")
    claim = runtime.claim_next(
        "cost-policy-worker",
        kinds={"test.cost-policy"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    inner = CountingAdapter(report_usage=False)
    adapter = MeteredLLMAdapter(
        inner,
        pricing_snapshot=_snapshot(
            {
                "currency": "USD",
                "input_microunits_per_million_tokens": 1_000_000,
                "output_microunits_per_million_tokens": 2_000_000,
                "request_microunits": 10,
            }
        ),
        checkpoint={"round": 0, "cost_microunits": 0},
    )
    token = bind_runtime_execution(context, turn_id="strict-post-usage")
    try:
        with pytest.raises(RuntimeBudgetExceeded) as blocked:
            list(adapter.stream([], []))
    finally:
        reset_runtime_execution(token)

    assert inner.calls == 1
    assert blocked.value.violation["phase"] == "post_usage"
    with UnitOfWork(app.state.database) as uow:
        entries = uow.task_runtime.list_cost_entries(plan["id"])
        events = uow.task_runtime.list_events(plan["id"])
    assert len(entries) == 1
    assert entries[0]["priced"] is False
    assert entries[0]["amount_microunits"] == 10
    assert [event["event_type"] for event in events].count(
        "runtime.cost_policy.blocked"
    ) == 1
    runtime.fail(claim, error="missing Provider usage", retryable=False)


def test_allow_policy_keeps_unpriced_provider_auditable(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "allow-unpriced", "allow")
    claim = runtime.claim_next(
        "cost-policy-worker",
        kinds={"test.cost-policy"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    inner = CountingAdapter(report_usage=True)
    adapter = MeteredLLMAdapter(
        inner,
        pricing_snapshot=_snapshot({}),
        checkpoint={"round": 0, "cost_microunits": 0},
    )
    token = bind_runtime_execution(context, turn_id="allow-unpriced")
    try:
        chunks = list(adapter.stream([], []))
    finally:
        reset_runtime_execution(token)

    assert inner.calls == 1
    assert chunks[-1].kind == "done"
    with UnitOfWork(app.state.database) as uow:
        entries = uow.task_runtime.list_cost_entries(plan["id"])
    assert len(entries) == 1
    assert entries[0]["priced"] is False
    runtime.fail(claim, error="test complete", retryable=False)
