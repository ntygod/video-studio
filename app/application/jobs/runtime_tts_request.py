"""Durable request ledger for Runtime-owned TTS Jobs."""

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
from app.store import UnitOfWork


def _slot(value: Any) -> str:
    return str(value or "default").strip()[:100] or "default"


def _snapshot(voice: str) -> dict[str, Any]:
    return {
        "version": 1,
        "source": "edge_tts_builtin",
        "provider_profile_id": "edge-tts",
        "provider_name": "Microsoft Edge TTS",
        "adapter": "edge-tts",
        "model_profile_id": f"edge-tts:{voice}"[:64],
        "model_id": str(voice)[:300],
        "capability_type": "tts",
        # The service has no authoritative price contract in this project.
        # Record the call as unpriced instead of inventing a zero cost.
        "pricing": {},
        "pricing_updated_at": None,
        "request_idempotency_header": "",
    }


def _request_sha(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
) -> str:
    encoded = json.dumps(
        {
            "text": text,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class RuntimeTtsRequest:
    binding: Any
    request: dict[str, Any]
    snapshot: dict[str, Any]

    @property
    def context(self):
        return self.binding.context

    def start(self) -> None:
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

    def response_started(self) -> None:
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            self.request = (
                uow.task_runtime.mark_provider_request_response_started(
                    self.request["id"],
                    plan_id=context.plan["id"],
                    task_id=context.task["id"],
                    attempt_id=context.attempt["id"],
                    claim_token=context.claim["claim_token"],
                )
            )

    def fail(self, exc: BaseException) -> None:
        context = self.context
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.fail_provider_request(
                self.request["id"],
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                error=str(exc) or exc.__class__.__name__,
                outcome_unknown=True,
            )
        self.request = dict(result["request"])
        # Edge TTS has no configured upstream idempotency contract.  A failed
        # external call therefore stops automatic replay for this Job attempt.
        raise RuntimeBudgetExceeded(result["violation"]) from None

    def complete(
        self,
        asset: dict[str, Any],
        *,
        text: str,
        audio_bytes: int = 0,
    ) -> dict[str, Any]:
        context = self.context
        usage = {
            "characters": len(text),
            "audio_bytes": max(0, int(audio_bytes)),
            "media_units": 1,
            "_provider_request_id": "",
            "_provider_model_id": str(
                self.snapshot.get("model_id") or ""
            ),
        }
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.record_provider_usage(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                usage_key=f"provider-request:{self.request['id']}",
                source_type="tts",
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
                provider_request_id="",
                response={
                    "asset_id": asset.get("id"),
                    "asset_uri": asset.get("uri"),
                    "asset_sha256": asset.get("sha256"),
                    "asset_kind": asset.get("kind"),
                },
                usage=usage,
                cost_entry_id=str(result["entry"]["id"]),
            )
        self.request = completed
        task_usage = dict(result.get("task_usage") or {})
        context.usage.update(task_usage)
        violation = (result.get("budget_state") or {}).get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        return result


def prepare_runtime_tts_request(
    database,
    *,
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    job_id: str,
    runtime_generation: int,
    request_slot: str = "default",
) -> RuntimeTtsRequest | None:
    binding = current_runtime_execution()
    if binding is None:
        return None
    context = binding.context
    with UnitOfWork(database) as uow:
        budget = uow.task_runtime.check_provider_budget(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
        )
    if budget.get("violation"):
        raise RuntimeBudgetExceeded(budget["violation"])

    generation = max(1, int(runtime_generation))
    normalized_slot = _slot(request_slot)
    snapshot = _snapshot(voice)
    with UnitOfWork(database) as uow:
        request = uow.task_runtime.prepare_provider_request(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
            request_key=(
                f"tts:{context.task['id']}:job:{job_id}:"
                f"generation:{generation}:slot:{normalized_slot}"
            ),
            source_type="tts",
            provider_snapshot=snapshot,
            request_sha256=_request_sha(text, voice, rate, pitch),
            request_summary={
                "job_id": job_id,
                "runtime_generation": generation,
                "request_slot": normalized_slot,
                "capability": "tts",
                "voice": voice,
                "text_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
                "pricing_snapshot": deepcopy(snapshot),
            },
            idempotency_header="",
        )
    return RuntimeTtsRequest(binding, dict(request), snapshot)


def reconcile_existing_tts_asset(
    database,
    asset: dict[str, Any],
    *,
    request_slot: str,
    text: str,
    audio_bytes: int = 0,
) -> None:
    binding = current_runtime_execution()
    if binding is None:
        return
    context = binding.context
    normalized_slot = _slot(request_slot)
    with UnitOfWork(database) as uow:
        requests = uow.task_runtime.list_provider_requests(
            context.plan["id"],
            limit=500,
        )
    matching = [
        request
        for request in requests
        if request["task_id"] == context.task["id"]
        and _slot(
            (request.get("request_summary") or {}).get("request_slot")
        )
        == normalized_slot
    ]
    if not matching or matching[0]["status"] in {"completed", "resolved"}:
        return
    request = matching[0]
    summary = dict(request.get("request_summary") or {})
    snapshot = dict(summary.get("pricing_snapshot") or _snapshot(""))
    RuntimeTtsRequest(binding, dict(request), snapshot).complete(
        asset,
        text=text,
        audio_bytes=audio_bytes,
    )


__all__ = [
    "RuntimeTtsRequest",
    "prepare_runtime_tts_request",
    "reconcile_existing_tts_asset",
]
