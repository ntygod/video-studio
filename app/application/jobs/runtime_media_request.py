"""Durable Provider request sessions for Runtime-owned media Jobs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.application.runtime_governance import (
    RuntimeBudgetExceeded,
    current_runtime_execution,
)
from app.domain.provider_pricing import normalize_model_pricing
from app.integrations.provider_request import (
    bind_provider_request,
    provider_idempotency_header,
    reset_provider_request,
)
from app.store import UnitOfWork


def _snapshot(provider, capability, parameters):
    models = list(provider.get("models") or [])
    if not models:
        raise RuntimeError("media Provider has no model profile")
    requested = str(parameters.get("model") or "")
    selected = None
    if requested:
        selected = next(
            (m for m in models if str(m.get("model_id") or "") == requested),
            None,
        )
        if selected is None:
            raise RuntimeError(
                f"media Provider model is not available: {requested}"
            )
    if selected is None:
        selected = next(
            (m for m in models if m.get("is_default")),
            models[0],
        )
    return {
        "version": 1,
        "source": "model_profile",
        "provider_profile_id": str(provider.get("id") or ""),
        "provider_name": str(provider.get("name") or ""),
        "adapter": str(provider.get("adapter") or ""),
        "model_profile_id": str(selected.get("id") or ""),
        "model_id": str(selected.get("model_id") or ""),
        "capability_type": str(capability),
        "pricing": normalize_model_pricing(selected.get("pricing")),
        "pricing_updated_at": selected.get("pricing_updated_at"),
        "request_idempotency_header": provider_idempotency_header(provider),
    }


def _request_sha(capability, prompt, parameters, model_id):
    encoded = json.dumps(
        {
            "capability": capability,
            "prompt": prompt,
            "parameters": parameters,
            "model_id": model_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict(plan):
    policy = dict(plan.get("policy") or {})
    provider_policy = policy.get("provider_cost_policy") or {}
    return bool(
        isinstance(provider_policy, dict)
        and provider_policy.get("unpriced_provider_mode") == "block"
    )


def _raise_unpriced(binding, snapshot, phase, cost_entry_id=""):
    context = binding.context
    with UnitOfWork(context.runtime.database) as uow:
        result = uow.task_runtime.record_unpriced_provider_violation(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
            phase=phase,
            provider_snapshot=snapshot,
            cost_entry_id=cost_entry_id,
        )
    raise RuntimeBudgetExceeded(result["violation"])


@dataclass(slots=True)
class RuntimeMediaRequest:
    binding: Any
    request: dict[str, Any]
    snapshot: dict[str, Any]

    @property
    def context(self):
        return self.binding.context

    def start(self):
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.start_provider_request(
                self.request["id"],
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
            )
        if result.get("violation"):
            raise RuntimeBudgetExceeded(result["violation"])
        self.request = dict(result["request"])
        return bind_provider_request(
            request_id=str(self.request["id"]),
            idempotency_key=str(self.request["idempotency_key"]),
            idempotency_header=str(self.request["idempotency_header"]),
        )

    def response_started(self):
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            self.request = uow.task_runtime.mark_provider_request_response_started(
                self.request["id"],
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
            )

    def fail(self, exc: BaseException, *, outcome_unknown: bool):
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.fail_provider_request(
                self.request["id"],
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                error=str(exc) or exc.__class__.__name__,
                outcome_unknown=outcome_unknown,
            )
        self.request = dict(result["request"])
        if not outcome_unknown or not self.request.get("idempotency_supported"):
            raise RuntimeBudgetExceeded(result["violation"]) from None

    def complete(self, asset, *, provider_task_id="", parameters=None):
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            current = uow.task_runtime.get_provider_request(self.request["id"])
            usage = {
                "media_units": 1,
                "duration_seconds": float(
                    (parameters or {}).get("duration_seconds") or 0
                ),
                "_provider_request_id": str(
                    current.get("provider_request_id") or ""
                ),
                "_provider_model_id": str(self.snapshot.get("model_id") or ""),
            }
            result = uow.task_runtime.record_provider_usage(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                usage_key=f"provider-request:{self.request['id']}",
                source_type=str(self.snapshot.get("capability_type") or "media"),
                provider_snapshot=self.snapshot,
                pricing_snapshot=self.snapshot,
                usage=usage,
            )
            completed = uow.task_runtime.complete_provider_request(
                self.request["id"],
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                provider_request_id=str(current.get("provider_request_id") or ""),
                response={
                    "asset_id": asset.get("id"),
                    "asset_uri": asset.get("uri"),
                    "asset_sha256": asset.get("sha256"),
                    "asset_kind": asset.get("kind"),
                    "provider_task_id": provider_task_id,
                },
                usage=usage,
                cost_entry_id=str(result["entry"]["id"]),
            )
        self.request = completed
        task_usage = dict(result.get("task_usage") or {})
        context.usage.update(task_usage)
        if _strict(context.plan) and not result["entry"].get("priced", False):
            _raise_unpriced(
                self.binding,
                self.snapshot,
                "post_usage",
                str(result["entry"]["id"]),
            )
        violation = (result.get("budget_state") or {}).get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        return result


def prepare_runtime_media_request(
    database,
    *,
    provider,
    capability,
    prompt,
    parameters,
    job_id,
    runtime_generation,
):
    binding = current_runtime_execution()
    if binding is None:
        return None
    context = binding.context
    snapshot = _snapshot(provider, capability, parameters)
    with UnitOfWork(database) as uow:
        budget = uow.task_runtime.check_provider_budget(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
        )
    if budget.get("violation"):
        raise RuntimeBudgetExceeded(budget["violation"])
    if _strict(context.plan) and not snapshot.get("pricing"):
        _raise_unpriced(binding, snapshot, "preflight")

    generation = max(1, int(runtime_generation))
    request_key = (
        f"media:{context.task['id']}:job:{job_id}:generation:{generation}"
    )
    with UnitOfWork(database) as uow:
        request = uow.task_runtime.prepare_provider_request(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
            request_key=request_key,
            source_type=str(capability),
            provider_snapshot=snapshot,
            request_sha256=_request_sha(
                capability,
                prompt,
                parameters,
                str(snapshot.get("model_id") or ""),
            ),
            request_summary={
                "job_id": job_id,
                "runtime_generation": generation,
                "capability": capability,
                "model_id": snapshot.get("model_id"),
                "prompt_sha256": hashlib.sha256(
                    str(prompt).encode("utf-8")
                ).hexdigest(),
                "parameter_keys": sorted(parameters),
                "pricing_snapshot": deepcopy(snapshot),
            },
            idempotency_header=str(
                snapshot.get("request_idempotency_header") or ""
            ),
        )
    return RuntimeMediaRequest(binding, dict(request), snapshot)


def reconcile_existing_media_asset(database, asset, *, parameters=None):
    binding = current_runtime_execution()
    if binding is None:
        return
    context = binding.context
    with UnitOfWork(database) as uow:
        requests = uow.task_runtime.list_provider_requests(
            context.plan["id"],
            limit=20,
        )
    matching = [r for r in requests if r["task_id"] == context.task["id"]]
    if not matching or matching[0]["status"] in {"completed", "resolved"}:
        return
    request = matching[0]
    summary = dict(request.get("request_summary") or {})
    snapshot = dict(summary.get("pricing_snapshot") or {})
    if not snapshot:
        snapshot = {
            "provider_profile_id": request.get("provider_profile_id"),
            "provider_name": request.get("provider_name"),
            "adapter": request.get("adapter"),
            "model_profile_id": request.get("model_profile_id"),
            "model_id": request.get("model_id"),
            "capability_type": request.get("capability_type"),
            "pricing": {},
        }
    RuntimeMediaRequest(binding, dict(request), snapshot).complete(
        asset,
        parameters=parameters,
    )


__all__ = [
    "RuntimeMediaRequest",
    "prepare_runtime_media_request",
    "reconcile_existing_media_asset",
    "reset_provider_request",
]
