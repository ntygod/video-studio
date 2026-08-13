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


class UsageAdapter:
    supports_native_tools = True
    model = "priced-model"

    def __init__(self, request_id="provider-response-1"):
        self.request_id = request_id
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        yield ChatChunk(kind="token", text="ok")
        yield ChatChunk(
            kind="usage",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "_provider_request_id": self.request_id,
                "_provider_model_id": self.model,
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


def _plan(runtime, project_id, key, max_cost=1_000):
    return runtime.create_plan(
        project_id=project_id,
        kind="test.cost",
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        budget={"max_cost_microunits": max_cost},
        tasks=[{"key": "execute", "type": "test.execute"}],
    )


def _snapshot():
    return {
        "version": 1,
        "provider_profile_id": "provider-1",
        "provider_name": "Provider",
        "adapter": "openai",
        "model_profile_id": "model-profile-1",
        "model_id": "priced-model",
        "capability_type": "llm",
        "pricing": {
            "currency": "USD",
            "input_microunits_per_million_tokens": 1_000_000,
            "output_microunits_per_million_tokens": 2_000_000,
            "request_microunits": 10,
        },
    }


def test_provider_cost_entry_is_exactly_once_and_updates_budget(
    app,
    client,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "cost-exactly-once")
    claim = runtime.claim_next("cost-worker", kinds={"test.cost"})
    assert claim is not None

    arguments = dict(
        plan_id=plan["id"],
        task_id=claim["task"]["id"],
        attempt_id=claim["attempt"]["id"],
        claim_token=claim["claim_token"],
        usage_key="llm:provider-1:response-1",
        source_type="llm",
        provider_snapshot=_snapshot(),
        pricing_snapshot=_snapshot(),
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "_provider_request_id": "response-1",
        },
    )
    with UnitOfWork(app.state.database) as uow:
        first = uow.task_runtime.record_provider_usage(**arguments)
    with UnitOfWork(app.state.database) as uow:
        replay = uow.task_runtime.record_provider_usage(**arguments)
        state = uow.task_runtime.budget_state(plan["id"])
        entries = uow.task_runtime.list_cost_entries(plan["id"])

    assert first["deduplicated"] is False
    assert replay["deduplicated"] is True
    assert first["entry"]["amount_microunits"] == 210
    assert len(entries) == 1
    assert state["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "tool_calls": 0,
        "cost_microunits": 210,
        "wall_seconds": state["usage"]["wall_seconds"],
        "cost_usd": 0.00021,
        "provider_calls": 1,
        "priced_calls": 1,
        "unpriced_calls": 0,
    }

    api_entries = client.get(
        f"/api/runtime-plans/{plan['id']}/costs"
    )
    assert api_entries.status_code == 200
    assert api_entries.json()[0]["amount_microunits"] == 210
    runtime.fail(claim, error="test complete", retryable=False)


def test_metered_adapter_commits_cost_before_budget_exception(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(
        runtime,
        project["id"],
        "cost-budget-crossing",
        max_cost=100,
    )
    claim = runtime.claim_next("cost-worker", kinds={"test.cost"})
    assert claim is not None
    context = _context(runtime, claim)
    checkpoint = {"round": 0, "cost_microunits": 0}
    adapter = MeteredLLMAdapter(
        UsageAdapter(),
        pricing_snapshot=_snapshot(),
        checkpoint=checkpoint,
    )
    token = bind_runtime_execution(context, turn_id="cost-turn")
    try:
        with pytest.raises(RuntimeBudgetExceeded) as exceeded:
            list(adapter.stream([], []))
    finally:
        reset_runtime_execution(token)

    assert exceeded.value.violation["dimension"] == "max_cost_microunits"
    assert context.usage["cost_microunits"] == 210
    assert checkpoint["cost_microunits"] == 210
    with UnitOfWork(app.state.database) as uow:
        state = uow.task_runtime.budget_state(plan["id"])
        entries = uow.task_runtime.list_cost_entries(plan["id"])
    assert state["usage"]["cost_microunits"] == 210
    assert len(entries) == 1
    runtime.fail(claim, error="cost budget exceeded", retryable=False)


def test_cost_at_limit_blocks_the_next_provider_call(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(
        runtime,
        project["id"],
        "cost-precheck",
        max_cost=100,
    )
    claim = runtime.claim_next("cost-worker", kinds={"test.cost"})
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.record_provider_usage(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            usage_key="llm:provider-1:at-limit",
            source_type="llm",
            provider_snapshot=_snapshot(),
            pricing_snapshot={
                **_snapshot(),
                "pricing": {
                    "currency": "USD",
                    "input_microunits_per_million_tokens": 1_000_000,
                },
            },
            usage={"prompt_tokens": 100, "completion_tokens": 0},
        )
    with UnitOfWork(app.state.database) as uow:
        state = uow.task_runtime.check_provider_budget(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
        )
    assert state["violation"]["dimension"] == "max_cost_microunits"
    assert state["violation"]["actual"] == 100
    runtime.fail(claim, error="precheck blocked", retryable=False)


def test_unpriced_provider_call_is_audited_without_fake_cost(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "unpriced-call")
    claim = runtime.claim_next("cost-worker", kinds={"test.cost"})
    assert claim is not None
    snapshot = {**_snapshot(), "pricing": {}}
    with UnitOfWork(app.state.database) as uow:
        recorded = uow.task_runtime.record_provider_usage(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            usage_key="llm:provider-1:unpriced",
            source_type="llm",
            provider_snapshot=snapshot,
            pricing_snapshot=snapshot,
            usage={
                "prompt_tokens": 25,
                "completion_tokens": 10,
                "_provider_request_id": "unpriced",
            },
        )
        state = uow.task_runtime.budget_state(plan["id"])

    assert recorded["entry"]["priced"] is False
    assert recorded["entry"]["amount_microunits"] == 0
    assert state["usage"]["provider_calls"] == 1
    assert state["usage"]["priced_calls"] == 0
    assert state["usage"]["unpriced_calls"] == 1
    assert state["usage"]["total_tokens"] == 35
    runtime.fail(claim, error="test complete", retryable=False)
