import threading

import httpx
import pytest

from app.application.commands import CommandBus, CommandContext, CreateJobCommand
from app.application.job_engine import JobEngine
from app.application.jobs.runtime_contract import MEDIA_JOB_PLAN_KIND
from app.application.jobs.runtime_executor_patch import _execute_runtime_job
from app.application.task_runtime_engine import (
    RetryableTaskError,
    TaskExecutionContext,
)
from app.integrations.media.client import _retryable_provider_error
from app.integrations.provider_request import (
    bind_provider_request,
    current_provider_request,
    reset_provider_request,
)
from app.store import UnitOfWork


class RecoveringMediaProvider:
    def __init__(self, *, fail_first: bool = False):
        self.fail_first = fail_first
        self.submit_calls = 0
        self.bindings = []

    def submit(self, _prompt, _params):
        self.submit_calls += 1
        self.bindings.append(current_provider_request())
        if self.fail_first and self.submit_calls == 1:
            raise httpx.ReadError("connection dropped")
        return "provider-task-1"

    def poll(self, _task_id):
        return "done", 1.0

    def fetch(self, _task_id):
        return b"generated-image"


def _provider(
    app,
    *,
    idempotency_header: str = "",
    priced: bool = True,
):
    pricing = {"request_microunits": 250_000} if priced else {}
    with UnitOfWork(app.state.database) as uow:
        return uow.providers.create(
            {
                "name": "Image Provider",
                "capability_type": "image",
                "adapter": "openai",
                "base_url": "https://provider.example/v1",
                "api_key": "secret",
                "enabled": True,
                "settings": {
                    "idempotency_header": idempotency_header,
                },
                "models": [
                    {
                        "name": "image-model",
                        "model_id": "image-model",
                        "capability_type": "image",
                        "is_default": True,
                        "pricing": pricing,
                    }
                ],
            }
        )


def _job(app, project_id: str, key: str):
    return CommandBus(app.state.database).execute(
        CreateJobCommand(
            project_id=project_id,
            job_type="media",
            payload={
                "capability": "image",
                "prompt": "雨夜街头",
                "parameters": {},
            },
        ),
        CommandContext(idempotency_key=key),
    ).result


def _claim(runtime, worker: str):
    claim = runtime.claim_next(
        worker,
        kinds={MEDIA_JOB_PLAN_KIND},
    )
    assert claim is not None
    return claim, TaskExecutionContext.from_claim(
        runtime,
        claim,
        30,
        threading.Event(),
    )


def test_runtime_media_request_records_asset_and_request_fee(
    app,
    project,
    monkeypatch,
):
    _provider(app, idempotency_header="Idempotency-Key")
    job = _job(app, project["id"], "media-ledger-success")
    provider = RecoveringMediaProvider()
    monkeypatch.setattr(
        "app.application.jobs.handlers.media.build_media_provider",
        lambda *_args, **_kwargs: provider,
    )
    engine = JobEngine(
        app.state.database,
        app.state.settings,
        app.state.media_store,
        workers=1,
    )
    runtime = engine._durable_job_engine.runtime
    claim, context = _claim(runtime, "media-worker")
    result = _execute_runtime_job(engine, context)
    runtime.complete(
        claim,
        result=result,
        checkpoint=context.checkpoint,
        usage=context.usage,
    )

    with UnitOfWork(app.state.database) as uow:
        request = uow.task_runtime.list_provider_requests(
            job["runtime_plan_id"]
        )[0]
        costs = uow.task_runtime.list_cost_entries(
            job["runtime_plan_id"]
        )
        saved = uow.jobs.get(job["id"])
    assert saved["status"] == "succeeded"
    assert request["status"] == "completed"
    assert request["response"]["asset_id"] == (
        saved["result"]["asset_id"]
    )
    assert request["dispatch_count"] == 1
    assert len(costs) == 1
    assert costs[0]["priced"] is True
    assert costs[0]["amount_microunits"] == 250_000
    assert provider.bindings[0].idempotency_header == "Idempotency-Key"


def test_media_request_retry_reuses_provider_idempotency_key(
    app,
    project,
    monkeypatch,
):
    _provider(app, idempotency_header="Idempotency-Key")
    job = _job(app, project["id"], "media-ledger-retry")
    provider = RecoveringMediaProvider(fail_first=True)
    monkeypatch.setattr(
        "app.application.jobs.handlers.media.build_media_provider",
        lambda *_args, **_kwargs: provider,
    )
    engine = JobEngine(
        app.state.database,
        app.state.settings,
        app.state.media_store,
        workers=1,
    )
    runtime = engine._durable_job_engine.runtime
    first, first_context = _claim(runtime, "media-worker-1")
    with pytest.raises(RetryableTaskError) as retryable:
        _execute_runtime_job(engine, first_context)
    runtime.fail(
        first,
        error=str(retryable.value),
        retryable=True,
        backoff_seconds=0,
        checkpoint=retryable.value.checkpoint,
    )

    second, second_context = _claim(runtime, "media-worker-2")
    result = _execute_runtime_job(engine, second_context)
    runtime.complete(
        second,
        result=result,
        checkpoint=second_context.checkpoint,
        usage=second_context.usage,
    )
    assert provider.submit_calls == 2
    assert provider.bindings[0].idempotency_key == (
        provider.bindings[1].idempotency_key
    )
    with UnitOfWork(app.state.database) as uow:
        request = uow.task_runtime.list_provider_requests(
            job["runtime_plan_id"]
        )[0]
        costs = uow.task_runtime.list_cost_entries(
            job["runtime_plan_id"]
        )
    assert request["status"] == "completed"
    assert request["dispatch_count"] == 2
    assert len(costs) == 1


def test_media_http_retry_requires_idempotency_header():
    error = httpx.ReadError("connection dropped")
    token = bind_provider_request(
        request_id="request-1",
        idempotency_key="stable-key",
        idempotency_header="",
    )
    try:
        assert _retryable_provider_error(error) is False
    finally:
        reset_provider_request(token)

    token = bind_provider_request(
        request_id="request-2",
        idempotency_key="stable-key",
        idempotency_header="Idempotency-Key",
    )
    try:
        assert _retryable_provider_error(error) is True
        response = httpx.Response(
            400,
            request=httpx.Request(
                "POST",
                "https://provider.example",
            ),
        )
        assert _retryable_provider_error(
            httpx.HTTPStatusError(
                "bad request",
                request=response.request,
                response=response,
            )
        ) is False
    finally:
        reset_provider_request(token)
