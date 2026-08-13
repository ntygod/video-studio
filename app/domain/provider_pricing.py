"""Canonical Provider model pricing and deterministic LLM cost calculation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

MICROUNITS_PER_USD = 1_000_000
TOKENS_PER_RATE_UNIT = 1_000_000

_RATE_FIELDS = (
    "input_microunits_per_million_tokens",
    "output_microunits_per_million_tokens",
    "cached_input_microunits_per_million_tokens",
    "request_microunits",
)
_USD_ALIASES = {
    "input_microunits_per_million_tokens": (
        "input_usd_per_million_tokens",
        "input_per_million_tokens",
    ),
    "output_microunits_per_million_tokens": (
        "output_usd_per_million_tokens",
        "output_per_million_tokens",
    ),
    "cached_input_microunits_per_million_tokens": (
        "cached_input_usd_per_million_tokens",
        "cached_input_per_million_tokens",
    ),
    "request_microunits": (
        "request_usd",
        "per_request",
    ),
}


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a non-negative number")
    integral = number.to_integral_value(rounding=ROUND_HALF_UP)
    if number != integral:
        raise ValueError(f"{field} must be an integer micro-unit value")
    return int(integral)


def usd_to_microunits(value: Any, *, field: str = "usd") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a non-negative number")
    return int(
        (number * MICROUNITS_PER_USD).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )


def normalize_model_pricing(value: Any) -> dict[str, Any]:
    """Return the canonical, integer-only USD pricing representation.

    Canonical token rate fields are micro-USD per one million tokens. Human
    facing aliases expressed in USD are accepted at API/import boundaries and
    converted immediately so every persisted snapshot is deterministic.
    """

    if value in (None, {}, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError("model pricing must be an object")

    currency = str(value.get("currency") or "USD").strip().upper()
    if currency != "USD":
        raise ValueError("only USD model pricing is currently supported")

    normalized: dict[str, Any] = {"currency": "USD"}
    for canonical in _RATE_FIELDS:
        if canonical in value and value[canonical] not in (None, ""):
            normalized[canonical] = _nonnegative_int(
                value[canonical],
                field=canonical,
            )
            continue
        for alias in _USD_ALIASES[canonical]:
            if alias in value and value[alias] not in (None, ""):
                normalized[canonical] = usd_to_microunits(
                    value[alias],
                    field=alias,
                )
                break

    # A currency-only object is not a price configuration.
    return normalized if len(normalized) > 1 else {}


def pricing_sha256(value: Any) -> str:
    normalized = normalize_model_pricing(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _usage_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def normalize_llm_usage(value: Any) -> dict[str, Any]:
    raw = deepcopy(value) if isinstance(value, dict) else {}
    prompt_tokens = _usage_int(
        raw.get("prompt_tokens", raw.get("input_tokens"))
    )
    completion_tokens = _usage_int(
        raw.get("completion_tokens", raw.get("output_tokens"))
    )
    prompt_details = (
        raw.get("prompt_tokens_details")
        or raw.get("input_tokens_details")
        or {}
    )
    cached_tokens = _usage_int(
        raw.get(
            "cached_prompt_tokens",
            prompt_details.get("cached_tokens")
            if isinstance(prompt_details, dict)
            else 0,
        )
    )
    cached_tokens = min(cached_tokens, prompt_tokens)
    usage_reported = any(
        key in raw
        for key in (
            "prompt_tokens",
            "input_tokens",
            "completion_tokens",
            "output_tokens",
        )
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_prompt_tokens": cached_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "usage_reported": usage_reported,
        "provider_request_id": str(
            raw.get("_provider_request_id")
            or raw.get("response_id")
            or raw.get("id")
            or ""
        ),
        "provider_model_id": str(
            raw.get("_provider_model_id")
            or raw.get("model_id")
            or raw.get("model")
            or ""
        ),
        "raw": raw,
    }


def _prorated_microunits(tokens: int, rate: int) -> int:
    numerator = max(0, int(tokens)) * max(0, int(rate))
    return int(
        (
            Decimal(numerator) / Decimal(TOKENS_PER_RATE_UNIT)
        ).to_integral_value(rounding=ROUND_HALF_UP)
    )


def price_llm_usage(pricing: Any, usage: Any) -> dict[str, Any]:
    normalized_pricing = normalize_model_pricing(pricing)
    normalized_usage = normalize_llm_usage(usage)
    prompt_tokens = int(normalized_usage["prompt_tokens"])
    completion_tokens = int(normalized_usage["completion_tokens"])
    cached_tokens = int(normalized_usage["cached_prompt_tokens"])
    ordinary_prompt_tokens = max(0, prompt_tokens - cached_tokens)

    input_rate = int(
        normalized_pricing.get(
            "input_microunits_per_million_tokens",
            0,
        )
    )
    output_rate = int(
        normalized_pricing.get(
            "output_microunits_per_million_tokens",
            0,
        )
    )
    cached_rate = int(
        normalized_pricing.get(
            "cached_input_microunits_per_million_tokens",
            input_rate,
        )
    )
    request_cost = int(
        normalized_pricing.get("request_microunits", 0)
    )
    ordinary_prompt_cost = _prorated_microunits(
        ordinary_prompt_tokens,
        input_rate,
    )
    cached_prompt_cost = _prorated_microunits(
        cached_tokens,
        cached_rate,
    )
    completion_cost = _prorated_microunits(
        completion_tokens,
        output_rate,
    )
    amount = (
        request_cost
        + ordinary_prompt_cost
        + cached_prompt_cost
        + completion_cost
    )
    token_pricing = any(
        key in normalized_pricing
        for key in (
            "input_microunits_per_million_tokens",
            "output_microunits_per_million_tokens",
            "cached_input_microunits_per_million_tokens",
        )
    )
    fully_priced = bool(normalized_pricing) and (
        not token_pricing or bool(normalized_usage["usage_reported"])
    )
    return {
        "currency": "USD",
        "priced": fully_priced,
        "amount_microunits": amount,
        "pricing": normalized_pricing,
        "pricing_sha256": pricing_sha256(normalized_pricing),
        "usage": normalized_usage,
        "breakdown": {
            "request_microunits": request_cost,
            "ordinary_prompt_tokens": ordinary_prompt_tokens,
            "ordinary_prompt_microunits": ordinary_prompt_cost,
            "cached_prompt_tokens": cached_tokens,
            "cached_prompt_microunits": cached_prompt_cost,
            "completion_tokens": completion_tokens,
            "completion_microunits": completion_cost,
        },
    }


def microunits_to_usd(value: Any) -> float:
    try:
        amount = max(0, int(value or 0))
    except (TypeError, ValueError):
        amount = 0
    return float(Decimal(amount) / Decimal(MICROUNITS_PER_USD))


__all__ = [
    "MICROUNITS_PER_USD",
    "TOKENS_PER_RATE_UNIT",
    "microunits_to_usd",
    "normalize_llm_usage",
    "normalize_model_pricing",
    "price_llm_usage",
    "pricing_sha256",
    "usd_to_microunits",
]
