"""Dynamic Provider request identity propagated to HTTP adapters."""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Mapping

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class ProviderRequestConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderRequestBinding:
    request_id: str
    idempotency_key: str
    idempotency_header: str


_current_provider_request: ContextVar[ProviderRequestBinding | None] = ContextVar(
    "video_studio_provider_request",
    default=None,
)


def provider_idempotency_header(provider: Mapping[str, object]) -> str:
    settings = provider.get("settings") or {}
    if not isinstance(settings, Mapping):
        return ""
    value = str(settings.get("idempotency_header") or "").strip()
    if not value:
        return ""
    if not _HEADER_NAME.fullmatch(value):
        raise ProviderRequestConfigurationError(
            "idempotency_header must be a valid HTTP header name"
        )
    return value


def bind_provider_request(
    *,
    request_id: str,
    idempotency_key: str,
    idempotency_header: str,
) -> Token:
    return _current_provider_request.set(
        ProviderRequestBinding(
            request_id=str(request_id or ""),
            idempotency_key=str(idempotency_key or ""),
            idempotency_header=str(idempotency_header or ""),
        )
    )


def reset_provider_request(token: Token) -> None:
    _current_provider_request.reset(token)


def current_provider_request() -> ProviderRequestBinding | None:
    return _current_provider_request.get()


def provider_request_headers(
    headers: Mapping[str, str] | None,
) -> dict[str, str]:
    result = {str(key): str(value) for key, value in (headers or {}).items()}
    binding = current_provider_request()
    if (
        binding is None
        or not binding.idempotency_header
        or not binding.idempotency_key
    ):
        return result
    existing_key = next(
        (
            key
            for key in result
            if key.lower() == binding.idempotency_header.lower()
        ),
        binding.idempotency_header,
    )
    result[existing_key] = binding.idempotency_key
    return result


__all__ = [
    "ProviderRequestBinding",
    "ProviderRequestConfigurationError",
    "bind_provider_request",
    "current_provider_request",
    "provider_idempotency_header",
    "provider_request_headers",
    "reset_provider_request",
]
