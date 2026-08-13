import httpx
import pytest

import app.application.reconciled_task_runtime as reconciled_module
from app.application.reconciled_task_runtime import ReconciledTaskRuntime
from app.application.runtime_governance import GovernedTaskRuntime
from app.integrations.provider_reconciliation import (
    ProviderReconciliationConfigurationError,
    provider_reconciliation_url,
    query_provider_request,
)


def _provider(path="/v1/requests/{request_id}"):
    return {
        "base_url": "https://provider.example/v1",
        "api_key": "secret",
        "settings": {
            "request_status_path": path,
            "request_status_field": "result.state",
            "request_status_provider_id_field": "id",
        },
    }


def test_provider_status_path_cannot_change_origin():
    with pytest.raises(ProviderReconciliationConfigurationError):
        provider_reconciliation_url(
            _provider("//evil.example/{request_id}"),
            "request-1",
        )
    with pytest.raises(ProviderReconciliationConfigurationError):
        provider_reconciliation_url(
            _provider("https://evil.example/{request_id}"),
            "request-1",
        )


def test_provider_status_query_maps_terminal_state(monkeypatch):
    calls = []

    def fake_get(url, *, headers, timeout):
        calls.append((url, headers, timeout))
        return httpx.Response(
            200,
            json={
                "id": "external-1",
                "result": {"state": "completed"},
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = query_provider_request(_provider(), "external-1")
    assert result.state == "completed"
    assert result.provider_request_id == "external-1"
    assert calls == [
        (
            "https://provider.example/v1/requests/external-1",
            {"Authorization": "Bearer secret"},
            20.0,
        )
    ]


def test_provider_status_query_keeps_pending_nonterminal(monkeypatch):
    def fake_get(url, *, headers, timeout):
        return httpx.Response(
            200,
            json={
                "id": "external-2",
                "result": {"state": "running"},
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = query_provider_request(_provider(), "external-2")
    assert result.state == "pending"
    assert result.status_value == "running"


def test_reconciled_runtime_runs_bounded_candidate_batch(monkeypatch):
    observed = {}

    class FakeRepository:
        def list_reconcilable_provider_request_ids(self, *, kinds, limit):
            observed["kinds"] = kinds
            observed["limit"] = limit
            return ["request-1"]

    class FakeUow:
        task_runtime = FakeRepository()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        GovernedTaskRuntime,
        "recover",
        lambda self, *, kinds=None, now=None: 2,
    )
    monkeypatch.setattr(
        reconciled_module,
        "UnitOfWork",
        lambda _database: FakeUow(),
    )

    def fake_reconcile(database, request_ids):
        observed["database"] = database
        observed["request_ids"] = request_ids
        return 1

    monkeypatch.setattr(
        reconciled_module,
        "reconcile_provider_requests",
        fake_reconcile,
    )
    runtime = ReconciledTaskRuntime("database")
    assert runtime.recover(kinds={"agent.turn"}, now=10) == 3
    assert observed == {
        "kinds": {"agent.turn"},
        "limit": 50,
        "database": "database",
        "request_ids": ["request-1"],
    }
