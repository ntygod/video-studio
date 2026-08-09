from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class MediaProviderError(RuntimeError):
    pass


def _base_url(provider: dict[str, Any]) -> str:
    return str(provider.get("base_url") or "").rstrip("/")


def _api_key(provider: dict[str, Any]) -> str:
    return str(provider.get("api_key") or "")


def _model(provider: dict[str, Any]) -> str:
    models = provider.get("models") or []
    if not models:
        raise MediaProviderError("provider has no model profile")
    return models[0]["model_id"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=6), reraise=True)
def generate_image(provider: dict[str, Any], prompt: str, parameters: dict[str, Any]) -> bytes:
    adapter = provider.get("adapter", "openai")
    url = _base_url(provider)
    key = _api_key(provider)
    model = _model(provider)
    if adapter == "grok2api":
        response = httpx.post(
            url + "/v1/images/generations",
            headers={"Authorization": "Bearer " + key},
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
            url + "/images/generations",
            headers={"Authorization": "Bearer " + key},
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
def generate_video(provider: dict[str, Any], prompt: str, parameters: dict[str, Any]) -> bytes:
    adapter = provider.get("adapter", "grok2api")
    url = _base_url(provider)
    key = _api_key(provider)
    model = _model(provider)
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
            url + "/v1/videos/generations",
            headers={"Authorization": "Bearer " + key},
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
            url + "/videos/generations",
            headers={"Authorization": "Bearer " + key},
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
