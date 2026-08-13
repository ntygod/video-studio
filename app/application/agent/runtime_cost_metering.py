"""Freeze Agent LLM pricing and meter every successful Provider response."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterator

from app.domain.provider_pricing import (
    normalize_llm_usage,
    normalize_model_pricing,
)
from app.application.runtime_governance import (
    RuntimeBudgetExceeded,
    current_runtime_execution,
)
from app.integrations.llm import build_adapter
from app.integrations.llm.base import ChatChunk, ToolSpec
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
        "version": 1,
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
    }
    checkpoint["llm_pricing_snapshot"] = deepcopy(snapshot)
    checkpoint.setdefault("cost_microunits", 0)
    return provider, snapshot


class MeteredLLMAdapter:
    """Transparent Adapter wrapper with exactly-once Provider cost entries."""

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
        self.model = getattr(inner, "model", pricing_snapshot.get("model_id"))

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

    def _record(self, binding, usage: dict[str, Any]) -> dict[str, Any]:
        context = binding.context
        normalized = normalize_llm_usage(usage)
        request_id = str(normalized.get("provider_request_id") or "")
        if request_id:
            usage_key = (
                "llm:"
                + str(self.pricing_snapshot.get("provider_profile_id") or "")
                + ":"
                + request_id
            )
        else:
            usage_key = (
                "llm:"
                + str(context.attempt["id"])
                + ":round:"
                + str(int(self.checkpoint.get("round") or 0))
            )
        with UnitOfWork(context.runtime.database) as uow:
            result = uow.task_runtime.record_provider_usage(
                plan_id=context.plan["id"],
                task_id=context.task["id"],
                attempt_id=context.attempt["id"],
                claim_token=context.claim["claim_token"],
                usage_key=usage_key,
                source_type="llm",
                provider_snapshot=self.pricing_snapshot,
                pricing_snapshot=self.pricing_snapshot,
                usage=usage,
            )
        task_usage = dict(result.get("task_usage") or {})
        context.usage.update(task_usage)
        self.checkpoint["cost_microunits"] = int(
            task_usage.get("cost_microunits") or 0
        )
        violation = (result.get("budget_state") or {}).get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        return result

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
        usage: dict[str, Any] = {}
        done_seen = False
        stream = self.inner.stream(
            messages,
            tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            for chunk in stream:
                if chunk.kind == "usage":
                    if chunk.usage:
                        usage.update(dict(chunk.usage))
                    continue
                if chunk.kind == "done":
                    done_seen = True
                    continue
                yield chunk
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

        result = self._record(binding, usage)
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
                "_cost_entry_id": result["entry"]["id"],
                "_cost_microunits": int(
                    result["entry"]["amount_microunits"]
                ),
            }
        )
        yield ChatChunk(kind="usage", usage=yielded_usage)
        if done_seen:
            yield ChatChunk(kind="done")
        else:
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
        # Freeze price before opening an external Provider request. A crash
        # after this commit can never reinterpret old usage with a new price.
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
