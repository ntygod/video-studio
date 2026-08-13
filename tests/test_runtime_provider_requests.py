import threading
import time

import httpx
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
from app.integrations.provider_request import current_provider_request
from app.store import UnitOfWork


class UsageAdapter:
    supports_native_tools = True
    model = "ledger-model"

    def __init__(self, *, request_id="provider-response-1"):
        self.request_id = request_id
        self.calls = 0
        self.bindings = []

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        self.bindings.append(current_provider_request())
        yield ChatChunk(kind="token", text="完成")
        yield ChatChunk(
            kind="usage",
            usage={
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "_provider_request_id": self.request_id,
                "_provider_model_id": self.model,
            },
        )
        yield ChatChunk(kind="done")


class BrokenAdapter:
    supports_native_tools = True
    model = "ledger-model"

    def __init__(self):
        self.calls = 0
        self.bindings = []

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        self.bindings.append(current_provider_request())
        yield ChatChunk(kind="token", text="部分")
        raise httpx.ReadError("connection dropped")


class NeverCalledAdapter:
    supports_native_tools = True
    model = "ledger-model"

    def __init__(self):
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        raise AssertionError("completed Provider response should be replayed")
        yield


def _context(runtime, claim):
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        30,
        threading.Event(),
    )


def _plan(runtime, project_id, key, *, max_attempts=3):
    return runtime.create_plan(
        project_id=project_id,
        kind="test.provider-request",
        subject_type="test",
        subject_id=key,
        idempotency_key=key,
        tasks=[
            {
                "key": "execute",
                "type": "test.execute",
                "max_attempts": max_attempts,
            }
        ],
    )


def _snapshot(*, idempotency_header=""):
    return {
        "version": 2,
        "provider_profile_id": "provider-1",
        "provider_name": "Provider",
        "adapter": "openai",
        "model_profile_id": "model-profile-1",
        "model_id": "ledger-model",
        "capability_type": "llm",
        "request_idempotency_header": idempotency_header,
        "pricing": {
            "currency": "USD",
            "input_microunits_per_million_tokens": 1_000_000,
            "output_microunits_per_million_tokens": 2_000_000,
        },
    }


def _run(adapter, context):
    token = bind_runtime_execution(context, turn_id="ledger-turn")
    try:
        return list(adapter.stream([{"role": "user", "content": "hi"}], []))
    finally:
        reset_runtime_execution(token)


def test_completed_provider_request_replays_without_second_external_call(
    app,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "provider-replay")
    claim = runtime.claim_next(
        "provider-worker",
        kinds={"test.provider-request"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    checkpoint = {"round": 0, "cost_microunits": 0}
    inner = UsageAdapter()
    chunks = _run(
        MeteredLLMAdapter(
            inner,
            pricing_snapshot=_snapshot(),
            checkpoint=checkpoint,
        ),
        context,
    )
    assert [chunk.kind for chunk in chunks] == ["token", "usage", "done"]
    assert inner.calls == 1

    replay_inner = NeverCalledAdapter()
    replayed = _run(
        MeteredLLMAdapter(
            replay_inner,
            pricing_snapshot=_snapshot(),
            checkpoint=checkpoint,
        ),
        context,
    )
    assert replay_inner.calls == 0
    assert replayed[0].text == "完成"
    assert replayed[1].usage["prompt_tokens"] == 20

    with UnitOfWork(app.state.database) as uow:
        requests = uow.task_runtime.list_provider_requests(plan["id"])
        costs = uow.task_runtime.list_cost_entries(plan["id"])
    assert len(requests) == 1
    assert requests[0]["status"] == "completed"
    assert requests[0]["dispatch_count"] == 1
    assert requests[0]["response"]["text"] == "完成"
    assert requests[0]["cost_entry_id"] == costs[0]["id"]
    assert len(costs) == 1
    runtime.fail(claim, error="test complete", retryable=False)


def test_unknown_request_without_idempotency_is_not_replayed(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "provider-unknown-no-key")
    claim = runtime.claim_next(
        "provider-worker",
        kinds={"test.provider-request"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    checkpoint = {"round": 0, "cost_microunits": 0}
    broken = BrokenAdapter()
    with pytest.raises(RuntimeBudgetExceeded) as first:
        _run(
            MeteredLLMAdapter(
                broken,
                pricing_snapshot=_snapshot(),
                checkpoint=checkpoint,
            ),
            context,
        )
    assert first.value.violation["dimension"] == (
        "provider_request_outcome_unknown"
    )
    never = NeverCalledAdapter()
    with pytest.raises(RuntimeBudgetExceeded):
        _run(
            MeteredLLMAdapter(
                never,
                pricing_snapshot=_snapshot(),
                checkpoint=checkpoint,
            ),
            context,
        )
    assert never.calls == 0
    with UnitOfWork(app.state.database) as uow:
        request = uow.task_runtime.list_provider_requests(plan["id"])[0]
    assert request["status"] == "outcome_unknown"
    assert request["dispatch_count"] == 1
    assert request["idempotency_supported"] is False
    runtime.fail(claim, error="unknown Provider outcome", retryable=False)


def test_unknown_request_with_idempotency_reuses_the_same_key(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "provider-unknown-with-key")
    claim = runtime.claim_next(
        "provider-worker",
        kinds={"test.provider-request"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    checkpoint = {"round": 0, "cost_microunits": 0}
    snapshot = _snapshot(idempotency_header="Idempotency-Key")
    broken = BrokenAdapter()
    with pytest.raises(httpx.ReadError):
        _run(
            MeteredLLMAdapter(
                broken,
                pricing_snapshot=snapshot,
                checkpoint=checkpoint,
            ),
            context,
        )
    successful = UsageAdapter(request_id="provider-recovered")
    chunks = _run(
        MeteredLLMAdapter(
            successful,
            pricing_snapshot=snapshot,
            checkpoint=checkpoint,
        ),
        context,
    )
    assert chunks[0].text == "完成"
    assert broken.bindings[0] is not None
    assert successful.bindings[0] is not None
    assert (
        broken.bindings[0].idempotency_key
        == successful.bindings[0].idempotency_key
    )
    assert successful.bindings[0].idempotency_header == "Idempotency-Key"
    with UnitOfWork(app.state.database) as uow:
        request = uow.task_runtime.list_provider_requests(plan["id"])[0]
        costs = uow.task_runtime.list_cost_entries(plan["id"])
    assert request["status"] == "completed"
    assert request["dispatch_count"] == 2
    assert request["provider_request_id"] == "provider-recovered"
    assert len(costs) == 1
    runtime.fail(claim, error="test complete", retryable=False)


def test_recovery_marks_interrupted_dispatch_unknown(app, project):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "provider-recover", max_attempts=2)
    claimed_at = time.time()
    claim = runtime.claim_next(
        "provider-worker",
        kinds={"test.provider-request"},
        lease_seconds=1,
        now=claimed_at,
    )
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        prepared = uow.task_runtime.prepare_provider_request(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            request_key="llm:recover:round:0",
            source_type="llm",
            provider_snapshot=_snapshot(),
            request_sha256="a" * 64,
            request_summary={"round": 0},
            now=claimed_at,
        )
        uow.task_runtime.start_provider_request(
            prepared["id"],
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            now=claimed_at,
        )
    recovered = runtime.recover(
        kinds={"test.provider-request"},
        now=claimed_at + 2,
    )
    assert recovered >= 2
    with UnitOfWork(app.state.database) as uow:
        request = uow.task_runtime.list_provider_requests(plan["id"])[0]
    assert request["status"] == "outcome_unknown"


def test_provider_request_api_lists_and_resolves_unknown(
    app,
    client,
    project,
):
    runtime = GovernedTaskRuntime(app.state.database)
    plan = _plan(runtime, project["id"], "provider-resolution-api")
    claim = runtime.claim_next(
        "provider-worker",
        kinds={"test.provider-request"},
    )
    assert claim is not None
    context = _context(runtime, claim)
    with pytest.raises(RuntimeBudgetExceeded):
        _run(
            MeteredLLMAdapter(
                BrokenAdapter(),
                pricing_snapshot=_snapshot(),
                checkpoint={"round": 0, "cost_microunits": 0},
            ),
            context,
        )
    response = client.get(
        f"/api/runtime-plans/{plan['id']}/provider-requests"
    )
    assert response.status_code == 200
    request = response.json()[0]
    resolved = client.post(
        f"/api/runtime-provider-requests/{request['id']}/resolve",
        json={
            "resolution": "completed_external",
            "note": "Provider dashboard confirms completion",
            "provider_request_id": "external-123",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["provider_request_id"] == "external-123"
    runtime.fail(claim, error="test complete", retryable=False)
