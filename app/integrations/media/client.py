from __future__ import annotations

import base64
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.integrations.provider_http import provider_endpoint, provider_headers
from app.integrations.provider_request import (
    current_provider_request,
    provider_request_headers,
)
from app.integrations.provider_response_identity import (
    observe_provider_response,
)


class MediaProviderError(RuntimeError):
    pass


def _model(provider: dict[str, Any], model: str | None = None) -> str:
    models = provider.get("models") or []
    if not models:
        raise MediaProviderError("provider has no model profile")
    if model:
        for item in models:
            if item.get("model_id") == model:
                return model
    for item in models:
        if item.get("is_default"):
            return str(item["model_id"])
    return str(models[0]["model_id"])


def _retryable_provider_error(exc: BaseException) -> bool:
    if (
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
    ):
        return False
    binding = current_provider_request()
    # Legacy Jobs retain their historical retry behavior. Runtime-owned Jobs
    # may repeat a POST only when the channel explicitly declares an
    # idempotency header; every attempt then carries the same stable value.
    return binding is None or bool(binding.idempotency_header)


def _headers(provider: dict[str, Any]) -> dict[str, str]:
    return provider_request_headers(provider_headers(provider))


def _observe(payload: dict[str, Any], model: str) -> None:
    observe_provider_response(
        str(payload.get("id") or payload.get("request_id") or ""),
        str(payload.get("model") or model),
    )


@retry(
    retry=retry_if_exception(_retryable_provider_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=6),
    reraise=True,
)
def generate_image(
    provider: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    model: str | None = None,
) -> bytes:
    adapter = str(provider.get("adapter") or "openai")
    model = _model(provider, model)
    if adapter not in {"grok2api", "openai"}:
        raise MediaProviderError(
            f"unsupported image adapter: {adapter}"
        )
    response = httpx.post(
        provider_endpoint(provider, "images/generations", "image_path"),
        headers=_headers(provider),
        json={
            "model": model,
            "prompt": prompt,
            "n": parameters.get("n", 1),
            "size": parameters.get("size", "1024x1024"),
            "response_format": parameters.get(
                "response_format",
                "b64_json",
            ),
        },
        timeout=300,
    )
    response.raise_for_status()
    payload = response.json()
    _observe(payload, model)
    candidates = payload.get("data") or []
    if not candidates:
        raise MediaProviderError("image provider returned no data")
    return _decode_image(candidates[0])


def _decode_image(item: dict[str, Any]) -> bytes:
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        data = httpx.get(str(item["url"]), timeout=120)
        data.raise_for_status()
        return data.content
    raise MediaProviderError(
        "image item has neither b64_json nor url"
    )


@retry(
    retry=retry_if_exception(_retryable_provider_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    reraise=True,
)
def generate_video(
    provider: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    model: str | None = None,
) -> bytes:
    adapter = str(provider.get("adapter") or "grok2api")
    model = _model(provider, model)
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "duration": parameters.get("duration_seconds", 5),
    }
    if adapter == "grok2api":
        payload["resolution"] = parameters.get("resolution", "720p")
        reference = parameters.get("reference_image_base64")
        if reference:
            payload["image"] = reference
    elif adapter != "openai":
        raise MediaProviderError(
            f"unsupported video adapter: {adapter}"
        )

    response = httpx.post(
        provider_endpoint(provider, "videos/generations", "video_path"),
        headers=_headers(provider),
        json=payload,
        timeout=900,
    )
    response.raise_for_status()
    data = response.json()
    _observe(data, model)
    video_url = (
        data.get("url")
        or data.get("video_url")
        or (data.get("data") or [{}])[0].get("url")
    )
    if not video_url:
        raise MediaProviderError("video provider returned no url")
    video = httpx.get(str(video_url), timeout=600)
    video.raise_for_status()
    return video.content
