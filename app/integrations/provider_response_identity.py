"""Provider response identity observed before full response persistence."""

from __future__ import annotations

from contextvars import ContextVar

from app.integrations.provider_request import current_provider_request

_observed: ContextVar[dict[str, dict[str, str]] | None] = ContextVar(
    "video_studio_provider_response_identity",
    default=None,
)


def observe_provider_response(
    provider_request_id: str,
    provider_model_id: str = "",
) -> None:
    binding = current_provider_request()
    if binding is None:
        return
    request_id = str(provider_request_id or "").strip()
    model_id = str(provider_model_id or "").strip()
    current = dict(_observed.get() or {})
    entry = dict(current.get(binding.request_id) or {})
    existing = str(entry.get("provider_request_id") or "")
    if request_id and existing and existing != request_id:
        raise RuntimeError(
            "Provider response request id changed during one dispatch"
        )
    if request_id:
        entry["provider_request_id"] = request_id
    if model_id:
        entry["provider_model_id"] = model_id
    current[binding.request_id] = entry
    _observed.set(current)


def observed_provider_response(request_id: str) -> dict[str, str]:
    return dict((_observed.get() or {}).get(str(request_id), {}))


def clear_observed_provider_response(request_id: str) -> None:
    current = dict(_observed.get() or {})
    current.pop(str(request_id), None)
    _observed.set(current or None)


__all__ = [
    "clear_observed_provider_response",
    "observe_provider_response",
    "observed_provider_response",
]
