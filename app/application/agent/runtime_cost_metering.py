"""Freeze Agent pricing and meter durable external Provider requests."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterator

import httpx

from app.application.runtime_governance import (
    RuntimeBudgetExceeded,
    current_runtime_execution,
)
from app.domain.provider_pricing import (
    normalize_llm_usage,
    normalize_model_pricing,
)
from app.integrations.llm import build_adapter
from app.integrations.llm.base import ChatChunk, ToolCall, ToolSpec
from app.integrations.provider_request import (
    bind_provider_request,
    provider_idempotency_header,
    reset_provider_request,
)
from app.store import UnitOfWork

_INSTALLED = False


def _checkpoint_usage(checkpoint: dict[str, Any]) -> dict[str, int]:
    return {
        "prompt_tokens": int(checkpoint.get("prompt_tokens") or 0),
        "completion_tokens": int(
            checkpoint.get("completion_tokens") or 0
        ),
        "cost_microunits": int(
            checkpoint.get("cost_microunits") or 0
        ),
    }


def _requires_priced_provider(binding) -> bool:
    policy = binding.context.plan.get("policy") or {}
    provider_policy = policy.get("provider_cost_policy") or {}
    return (
        isinstance(provider_policy, dict)
        and provider_policy.get("unpriced_provider_mode") == "block"
    )


def _selected_model(provider: dict[str, Any], model_id: str):
    models = list(provider.get("models") or [])
    selected = [
        model
        for model in models
        if str(model.get("model_id") or "") == model_id
    ]
    if not selected:
        raise RuntimeError(
            "Agent checkpoint LLM model is no longer available"
        )
    provider["models"] = selected + [
        model for model in models if model not in selected
    ]
    return selected[0]


def _load_provider_and_snapshot(
    database,
    checkpoint: dict[str, Any],
):
    provider_id = str(checkpoint.get("provider_id") or "")
    model_id = str(checkpoint.get("model_id") or "")
    if not provider_id:
        raise RuntimeError("Agent checkpoint has no frozen LLM provider")
    if not model_id:
        raise RuntimeError("Agent checkpoint has no frozen LLM model")
    with UnitOfWork(database) as uow:
        provider = uow.providers.get(
            provider_id,
            include_secret=True,
        )
    model = _selected_model(provider, model_id)

    existing = checkpoint.get("llm_pricing_snapshot")
    if isinstance(existing, dict) and existing:
        if (
            str(existing.get("provider_profile_id") or "")
            != provider_id
            or str(existing.get("model_id") or "") != model_id
        ):
            raise RuntimeError(
                "Agent LLM pricing snapshot identity changed"
            )
        return provider, deepcopy(existing)

    has_prior_usage = bool(
        int(checkpoint.get("prompt_tokens") or 0)
        or int(checkpoint.get("completion_tokens") or 0)
        or int(checkpoint.get("round") or 0)
    )
    pricing = (
        {}
        if has_prior_usage
        else normalize_model_pricing(model.get("pricing"))
    )
    snapshot = {
        "version": 2,
        "source": (
            "legacy_unpriced"
            if has_prior_usage
            else ("model_profile" if pricing else "model_unpriced")
        ),
        "provider_profile_id": provider_id,
        "provider_name": str(provider.get("name") or ""),
        "adapter": str(provider.get("adapter") or ""),
        "model_profile_id": str(model.get("id") or ""),
        "model_id": model_id,
        "capability_type": str(
            model.get("capability_type")
            or provider.get("capability_type")
            or "llm"
        ),
        "pricing": pricing,
        "pricing_updated_at": model.get("pricing_updated_at"),
        "request_idempotency_header": provider_idempotency_header(provider),
    }
    checkpoint["llm_pricing_snapshot"] = deepcopy(snapshot)
    checkpoint.setdefault("cost_microunits", 0)
    return provider, snapshot


def _block_unpriced_provider(
    binding,
    snapshot: dict[str, Any],
    *,
    phase: str,
    cost_entry_id: str = "",
) -> None:
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


def _request_fingerprint(
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[ToolSpec],
    max_tokens: int,
    temperature: float,
) -> str:
    payload = {
        "model_id": model_id,
        "messages": messages,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ],
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _known_provider_rejection(exc: BaseException) -> bool:
    return bool(
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
    )


class MeteredLLMAdapter:
    """Adapter wrapper with request replay, idempotency, and exact costs."""

    def __init__(
        self,
        inner,
        *,
        pricing_snapshot: dict[str, Any],
        checkpoint: dict[str, Any],
    ):
        self.inner = inner
        self.pricing_snapshot = deepcopy(pricing_snapshot)
        self.checkpoint = checkpoint
        self.supports_native_tools = bool(
            getattr(inner, "supports_native_tools", False)
        )
        self.model = getattr(
            inner,
            "model",
            pricing_snapshot.get("model_id"),
        )

    def _precheck(self, binding) -> None:
        context = binding.context
        with UnitOfWork(context.runtime.database) as uow:
            state = uow.task_runtime.check_provider_budget(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
            )
        violation = state.get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        if (
            _requires_priced_provider(binding)
            and not self.pricing_snapshot.get("pricing")
        ):
            _block_unpriced_provider(
                binding,
                self.pricing_snapshot,
                phase="preflight",
            )

    def _prepare_request(
        self,
        binding,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        context = binding.context
        round_index = int(self.checkpoint.get("round") or 0)
        request_key = (
            f"llm:{context.task['id']}:round:{round_index}"
        )
        request_sha256 = _request_fingerprint(
            model_id=str(self.pricing_snapshot.get("model_id") or self.model),
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        with UnitOfWork(context.runtime.database) as uow:
            return uow.task_runtime.prepare_provider_request(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                request_key=request_key,
                source_type="llm",
                provider_snapshot=self.pricing_snapshot,
                request_sha256=request_sha256,
                request_summary={
                    "round": round_index,
                    "model_id": str(
                        self.pricing_snapshot.get("model_id") or self.model
                    ),
                    "message_count": len(messages),
                    "tool_names": [tool.name for tool in tools],
                    "max_tokens": int(max_tokens),
                    "temperature": float(temperature),
                },
                idempotency_header=str(
                    self.pricing_snapshot.get(
                        "request_idempotency_header"
                    )
                    or ""
                ),
            )

    def _start_request(self, binding, request_id: str) -> dict[str, Any]:
        context = binding.context
        with UnitOfWork(context.runtime.database) as uow:
            return uow.task_runtime.start_provider_request(
                request_id,
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
            )

    def _mark_response_started(self, binding, request_id: str) -> None:
        context = binding.context
        with UnitOfWork(context.runtime.database) as uow:
            uow.task_runtime.mark_provider_request_response_started(
                request_id,
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
            )

    def _mark_failure(
        self,
        binding,
        request_id: str,
        exc: BaseException,
        *,
        outcome_unknown: bool,
    ) -> dict[str, Any]:
        context = binding.context
        with UnitOfWork(context.runtime.database) as uow:
            return uow.task_runtime.fail_provider_request(
                request_id,
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                error=str(exc) or exc.__class__.__name__,
                outcome_unknown=outcome_unknown,
            )

    def _record(
        self,
        binding,
        request: dict[str, Any],
        usage: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        context = binding.context
        normalized = normalize_llm_usage(usage)
        request_id = str(request["id"])
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.record_provider_usage(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                usage_key=f"provider-request:{request_id}",
                source_type="llm",
                provider_snapshot=self.pricing_snapshot,
                pricing_snapshot=self.pricing_snapshot,
                usage=usage,
            )
            uow.task_runtime.complete_provider_request(
                request_id,
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                provider_request_id=str(
                    normalized.get("provider_request_id") or ""
                ),
                response=response,
                usage=usage,
                cost_entry_id=str(result["entry"]["id"]),
            )
        task_usage = dict(result.get("task_usage") or {})
        context.usage.update(task_usage)
        self.checkpoint["cost_microunits"] = int(
            task_usage.get("cost_microunits") or 0
        )
        if (
            _requires_priced_provider(binding)
            and not result["entry"].get("priced", False)
        ):
            _block_unpriced_provider(
                binding,
                self.pricing_snapshot,
                phase="post_usage",
                cost_entry_id=str(result["entry"]["id"]),
            )
        violation = (result.get("budget_state") or {}).get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        return result

    def _replay(self, binding, request_id: str) -> Iterator[ChatChunk]:
        context = binding.context
        with UnitOfWork(context.runtime.database) as uow:
            replay = uow.task_runtime.replay_provider_request(request_id)
        task_usage = dict(replay.get("task_usage") or {})
        context.usage.update(task_usage)
        self.checkpoint["cost_microunits"] = int(
            task_usage.get("cost_microunits") or 0
        )
        request = dict(replay["request"])
        response = dict(request.get("response") or {})
        text = str(response.get("text") or "")
        if text:
            yield ChatChunk(kind="token", text=text)
        for item in response.get("tool_calls") or []:
            yield ChatChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    arguments=dict(item.get("arguments") or {}),
                ),
            )
        usage = dict(response.get("usage") or request.get("usage") or {})
        entry = replay.get("cost_entry") or {}
        if entry:
            usage["_cost_entry_id"] = str(entry.get("id") or "")
            usage["_cost_microunits"] = int(
                entry.get("amount_microunits") or 0
            )
        usage["_provider_request_ledger_id"] = request_id
        yield ChatChunk(kind="usage", usage=usage)
        yield ChatChunk(kind="done")

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        binding = current_runtime_execution()
        if binding is None:
            yield from self.inner.stream(
                messages,
                tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return

        self._precheck(binding)
        request = self._prepare_request(
            binding,
            messages,
            tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if request["status"] == "completed":
            yield from self._replay(binding, str(request["id"]))
            return
        started = self._start_request(binding, str(request["id"]))
        violation = started.get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        if started.get("replay"):
            yield from self._replay(binding, str(request["id"]))
            return
        request = dict(started["request"])

        usage: dict[str, Any] = {}
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        response_started = False
        provider_token = bind_provider_request(
            request_id=str(request["id"]),
            idempotency_key=str(request["idempotency_key"]),
            idempotency_header=str(request["idempotency_header"]),
        )
        try:
            stream = self.inner.stream(
                messages,
                tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            try:
                for chunk in stream:
                    if not response_started:
                        self._mark_response_started(
                            binding,
                            str(request["id"]),
                        )
                        response_started = True
                    if chunk.kind == "usage":
                        if chunk.usage:
                            usage.update(dict(chunk.usage))
                        continue
                    if chunk.kind == "done":
                        continue
                    if chunk.kind == "token":
                        text_parts.append(chunk.text)
                    elif (
                        chunk.kind == "tool_call"
                        and chunk.tool_call is not None
                    ):
                        tool_calls.append(
                            {
                                "id": chunk.tool_call.id,
                                "name": chunk.tool_call.name,
                                "arguments": deepcopy(
                                    chunk.tool_call.arguments
                                ),
                            }
                        )
                    yield chunk
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
        except GeneratorExit:
            try:
                self._mark_failure(
                    binding,
                    str(request["id"]),
                    GeneratorExit("Provider response consumer closed"),
                    outcome_unknown=True,
                )
            except BaseException:
                pass
            raise
        except Exception as exc:
            known_rejection = _known_provider_rejection(exc)
            result = self._mark_failure(
                binding,
                str(request["id"]),
                exc,
                outcome_unknown=not known_rejection,
            )
            if known_rejection or not request.get("idempotency_supported"):
                raise RuntimeBudgetExceeded(result["violation"]) from None
            raise
        finally:
            reset_provider_request(provider_token)

        response = {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "usage": deepcopy(usage),
        }
        result = self._record(binding, request, usage, response)
        normalized = dict(result["entry"].get("usage") or {})
        yielded_usage = dict(usage)
        yielded_usage.update(
            {
                "prompt_tokens": int(
                    normalized.get("prompt_tokens") or 0
                ),
                "completion_tokens": int(
                    normalized.get("completion_tokens") or 0
                ),
                "cached_prompt_tokens": int(
                    normalized.get("cached_prompt_tokens") or 0
                ),
                "_provider_request_id": str(
                    normalized.get("provider_request_id") or ""
                ),
                "_provider_model_id": str(
                    normalized.get("provider_model_id") or ""
                ),
                "_provider_request_ledger_id": str(request["id"]),
                "_cost_entry_id": result["entry"]["id"],
                "_cost_microunits": int(
                    result["entry"]["amount_microunits"]
                ),
            }
        )
        yield ChatChunk(kind="usage", usage=yielded_usage)
        yield ChatChunk(kind="done")


def install_agent_cost_metering() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from app.application.agent import durable_loop

    original_usage = durable_loop._usage
    original_adapter = durable_loop._adapter_for_checkpoint

    def costed_usage(checkpoint: dict[str, Any]) -> dict[str, int]:
        usage = dict(original_usage(checkpoint))
        usage["cost_microunits"] = int(
            checkpoint.get("cost_microunits") or 0
        )
        return usage

    def costed_adapter_for_checkpoint(database, checkpoint):
        binding = current_runtime_execution()
        if binding is None:
            return original_adapter(database, checkpoint)
        provider, snapshot = _load_provider_and_snapshot(
            database,
            checkpoint,
        )
        # Freeze price and idempotency contract before opening an external
        # Provider request. Recovery never reinterprets an existing request.
        binding.context.heartbeat(
            checkpoint=deepcopy(checkpoint),
            usage=costed_usage(checkpoint),
        )
        adapter = build_adapter(
            provider,
            model_id=str(checkpoint.get("model_id") or "") or None,
        )
        return MeteredLLMAdapter(
            adapter,
            pricing_snapshot=snapshot,
            checkpoint=checkpoint,
        )

    durable_loop._usage = costed_usage
    durable_loop._adapter_for_checkpoint = costed_adapter_for_checkpoint


__all__ = [
    "MeteredLLMAdapter",
    "install_agent_cost_metering",
]
