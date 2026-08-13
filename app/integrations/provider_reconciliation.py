"""Same-origin Provider request status queries for durable reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping
from urllib.parse import quote, urljoin, urlsplit

import httpx

from app.integrations.provider_http import (
    provider_api_root,
    provider_headers,
    provider_settings,
)

ReconciliationState = Literal["pending", "completed", "failed", "unknown"]


class ProviderReconciliationConfigurationError(ValueError):
    pass


class ProviderReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderReconciliationObservation:
    state: ReconciliationState
    status_value: str
    provider_request_id: str
    response: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "status_value": self.status_value,
            "provider_request_id": self.provider_request_id,
            "response": self.response,
        }


def _lookup(value: Any, path: str) -> Any:
    current = value
    for part in [item for item in str(path or "").split(".") if item]:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _values(settings: Mapping[str, Any], key: str, defaults: set[str]) -> set[str]:
    raw = settings.get(key)
    if raw is None:
        return defaults
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        raise ProviderReconciliationConfigurationError(
            f"{key} must be a list or comma-separated string"
        )
    return {
        str(item).strip().lower()
        for item in items
        if str(item).strip()
    }


def provider_reconciliation_supported(provider: Mapping[str, Any]) -> bool:
    settings = provider_settings(dict(provider))
    return bool(str(settings.get("request_status_path") or "").strip())


def provider_reconciliation_url(
    provider: Mapping[str, Any],
    provider_request_id: str,
) -> str:
    settings = provider_settings(dict(provider))
    template = str(settings.get("request_status_path") or "").strip()
    if not template:
        raise ProviderReconciliationConfigurationError(
            "Provider has no request_status_path"
        )
    if "://" in template or template.startswith("//"):
        raise ProviderReconciliationConfigurationError(
            "request_status_path must remain on the Provider host"
        )
    if "{request_id}" not in template:
        raise ProviderReconciliationConfigurationError(
            "request_status_path must contain {request_id}"
        )
    request_id = str(provider_request_id or "").strip()
    if not request_id:
        raise ProviderReconciliationConfigurationError(
            "Provider request id is required for reconciliation"
        )
    rendered = template.replace(
        "{request_id}",
        quote(request_id, safe=""),
    )
    root = provider_api_root(dict(provider)).rstrip("/") + "/"
    url = urljoin(root, rendered)
    root_parts = urlsplit(root)
    url_parts = urlsplit(url)
    if (
        url_parts.scheme != root_parts.scheme
        or url_parts.netloc != root_parts.netloc
    ):
        raise ProviderReconciliationConfigurationError(
            "request_status_path changed the Provider origin"
        )
    return url


def query_provider_request(
    provider: Mapping[str, Any],
    provider_request_id: str,
) -> ProviderReconciliationObservation:
    settings = provider_settings(dict(provider))
    url = provider_reconciliation_url(provider, provider_request_id)
    try:
        timeout = float(settings.get("request_status_timeout_seconds") or 20)
    except (TypeError, ValueError) as exc:
        raise ProviderReconciliationConfigurationError(
            "request_status_timeout_seconds must be numeric"
        ) from exc
    timeout = max(1.0, min(timeout, 120.0))
    try:
        response = httpx.get(
            url,
            headers=provider_headers(dict(provider)),
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderReconciliationError(
            f"Provider request status query failed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderReconciliationError(
            "Provider request status response must be a JSON object"
        )

    status_field = str(settings.get("request_status_field") or "status")
    status_value = str(_lookup(payload, status_field) or "").strip()
    normalized = status_value.lower()
    completed = _values(
        settings,
        "request_status_completed_values",
        {"completed", "succeeded", "done", "success"},
    )
    failed = _values(
        settings,
        "request_status_failed_values",
        {"failed", "error", "canceled", "cancelled"},
    )
    pending = _values(
        settings,
        "request_status_pending_values",
        {"queued", "pending", "running", "processing", "in_progress"},
    )
    if normalized in completed:
        state: ReconciliationState = "completed"
    elif normalized in failed:
        state = "failed"
    elif normalized in pending:
        state = "pending"
    else:
        state = "unknown"

    id_field = str(settings.get("request_status_provider_id_field") or "id")
    observed_id = str(_lookup(payload, id_field) or provider_request_id)
    return ProviderReconciliationObservation(
        state=state,
        status_value=status_value,
        provider_request_id=observed_id,
        response=payload,
    )


__all__ = [
    "ProviderReconciliationConfigurationError",
    "ProviderReconciliationError",
    "ProviderReconciliationObservation",
    "provider_reconciliation_supported",
    "provider_reconciliation_url",
    "query_provider_request",
]
