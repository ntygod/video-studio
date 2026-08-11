from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.integrations.provider_http import provider_endpoint, provider_headers


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
    return models[0]["model_id"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=6), reraise=True)
def generate_image(
    provider: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    model: str | None = None,
) -> bytes:
    adapter = provider.get("adapter", "openai")
    model = _model(provider, model)
    if adapter == "grok2api":
        response = httpx.post(
            provider_endpoint(provider, "images/generations", "image_path"),
            headers=provider_headers(provider),
            json={
                "model": model,
                "prompt": prompt,
                "n": parameters.get("n", 1),
                "size": parameters.get("size", "1024x1024"),
                "response_format": parameters.get("response_format", "b64_json"),
            },
            timeout=300,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("data") or []
        if not candidates:
            raise MediaProviderError("image provider returned no data")
        return _decode_image(candidates[0])
    if adapter == "openai":
        response = httpx.post(
            provider_endpoint(provider, "images/generations", "image_path"),
            headers=provider_headers(provider),
            json={
                "model": model,
                "prompt": prompt,
                "n": parameters.get("n", 1),
                "size": parameters.get("size", "1024x1024"),
                "response_format": parameters.get("response_format", "b64_json"),
            },
            timeout=300,
        )
        response.raise_for_status()
        candidates = response.json().get("data") or []
        if not candidates:
            raise MediaProviderError("image provider returned no data")
        return _decode_image(candidates[0])
    raise MediaProviderError(f"unsupported image adapter: {adapter}")


def _decode_image(item: dict[str, Any]) -> bytes:
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        data = httpx.get(item["url"], timeout=120)
        data.raise_for_status()
        return data.content
    raise MediaProviderError("image item has neither b64_json nor url")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
def generate_video(
    provider: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    model: str | None = None,
) -> bytes:
    adapter = provider.get("adapter", "grok2api")
    model = _model(provider, model)
    if adapter == "grok2api":
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "duration": parameters.get("duration_seconds", 5),
            "resolution": parameters.get("resolution", "720p"),
        }
        reference = parameters.get("reference_image_base64")
        if reference:
            payload["image"] = reference
        response = httpx.post(
            provider_endpoint(provider, "videos/generations", "video_path"),
            headers=provider_headers(provider),
            json=payload,
            timeout=900,
        )
        response.raise_for_status()
        data = response.json()
        video_url = data.get("url") or data.get("video_url") or (data.get("data") or [{}])[0].get("url")
        if not video_url:
            raise MediaProviderError("video provider returned no url")
        video = httpx.get(str(video_url), timeout=600)
        video.raise_for_status()
        return video.content
    if adapter == "openai":
        response = httpx.post(
            provider_endpoint(provider, "videos/generations", "video_path"),
            headers=provider_headers(provider),
            json={"model": model, "prompt": prompt, "duration": parameters.get("duration_seconds", 5)},
            timeout=900,
        )
        response.raise_for_status()
        data = response.json()
        video_url = data.get("url") or (data.get("data") or [{}])[0].get("url")
        if not video_url:
            raise MediaProviderError("video provider returned no url")
        video = httpx.get(str(video_url), timeout=600)
        video.raise_for_status()
        return video.content
    raise MediaProviderError(f"unsupported video adapter: {adapter}")
