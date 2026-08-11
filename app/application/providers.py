import json
from pathlib import Path
from typing import Any

import httpx

from app.integrations.provider_http import provider_endpoint, provider_headers


DEFAULT_CAPABILITIES = {
    "llm": {"structured_output": True, "vision": False},
    "image": {
        "aspect_ratios": ["1:1", "16:9", "9:16", "3:4", "4:3"],
        "resolutions": ["480p", "720p", "1080p"],
        "reference_images": True,
    },
    "video": {
        "aspect_ratios": ["1:1", "16:9", "9:16", "3:4", "4:3"],
        "resolutions": ["480p", "720p", "1080p"],
        "duration_seconds": {"min": 1, "max": 15},
        "reference_images": True,
    },
    "tts": {"multi_voice": True, "emotion": False},
}


class ProviderDiscoveryError(RuntimeError):
    pass


def _map_capability(value: Any) -> str | None:
    """把上游常见的 capability 枚举映射到本系统能力类型。"""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"llm", "chat", "text", "responses", "completion", "language", "reasoning", "conversation"}:
        return "llm"
    if text in {"image", "image_edit", "imageedit", "img", "draw"}:
        return "image"
    if text in {"video"}:
        return "video"
    if text in {"tts", "speech", "voice", "audio", "stt", "asr", "whisper"}:
        return "tts"
    if text in {"embedding", "embed", "rerank"}:
        return "embedding"
    return None


def _infer_capability(model_id: str, name: str, item: dict[str, Any], fallback: str) -> str:
    """从上游字段、模型 ID/名称推断真实能力；grok2api 列表不含 capability 字段，只能按 ID 推断。"""
    for key in ("capability", "capability_type", "type", "kind"):
        value = item.get(key)
        mapped = _map_capability(value)
        if mapped:
            return mapped
    for key in ("capabilities", "modalities", "input_modalities", "endpoint_capabilities"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                mapped = _map_capability(entry)
                if mapped:
                    return mapped
        elif isinstance(value, dict):
            for entry in value.values():
                mapped = _map_capability(entry)
                if mapped:
                    return mapped

    haystack = f"{model_id} {name}".lower()
    if any(token in haystack for token in ("video", "veo", "sora", "kling", "runway", "pika", "hailuo", "luma", "dreamina")):
        return "video"
    if any(token in haystack for token in ("image", "imagine", "dall-e", "dalle", "flux", "sdxl", "midjourney", "stable-diffusion")):
        return "image"
    if any(token in haystack for token in ("tts", "speech", "voice", "audio", "whisper", "stt", "asr", "suno")):
        return "tts"
    if any(token in haystack for token in ("embedding", "embed", "rerank")):
        return "embedding"

    # OpenAI 兼容的 /models 绝大多数是聊天模型；图片/视频模型一般会带
    # image/video 之类的名字。识别不到时默认 llm，避免整个列表被标成
    # 当前渠道类型（例如视频渠道把 grok-4.5 也标成视频）。
    return "llm"


def _model_collection(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "models", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("models") or value.get("data") or value.get("items")
            if isinstance(nested, list):
                return nested
    return []


def _normalize_models(payload: Any, fallback: str = "llm") -> list[dict[str, str]]:
    models: dict[str, dict[str, str]] = {}
    for item in _model_collection(payload):
        raw_item: dict[str, Any] = {}
        if isinstance(item, str):
            model_id = item.strip()
            name = model_id
            owned_by = ""
        elif isinstance(item, dict):
            raw_item = item
            model_id = str(
                item.get("id")
                or item.get("model_id")
                or item.get("model")
                or item.get("name")
                or ""
            ).strip()
            name = str(
                item.get("display_name")
                or item.get("displayName")
                or item.get("name")
                or model_id
            ).strip()
            owned_by = str(item.get("owned_by") or item.get("ownedBy") or "").strip()
        else:
            continue
        if model_id and model_id not in models:
            models[model_id] = {
                "model_id": model_id,
                "name": name or model_id,
                "owned_by": owned_by,
                "capability_type": _infer_capability(model_id, name, raw_item, fallback),
            }
    return [models[key] for key in sorted(models, key=str.lower)]


def discover_provider_models(provider: dict[str, Any]) -> dict[str, Any]:
    try:
        url = provider_endpoint(provider, "models", "models_path")
        response = httpx.get(url, headers=provider_headers(provider), timeout=20)
        response.raise_for_status()
        models = _normalize_models(
            response.json(),
            fallback=str(provider.get("capability_type") or "llm"),
        )
    except httpx.HTTPStatusError as exc:
        raise ProviderDiscoveryError(f"上游模型接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ProviderDiscoveryError(f"无法连接上游模型接口：{exc.__class__.__name__}") from exc
    except (ValueError, TypeError) as exc:
        raise ProviderDiscoveryError(str(exc)) from exc
    if not models:
        raise ProviderDiscoveryError("上游接口连接成功，但没有返回可识别的模型")
    return {"models": models, "source_url": url}


def import_provider_file_once(uow, path: Path) -> int:
    if not path.exists() or uow.providers.list():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for capability_type, config in data.items():
        if not isinstance(config, dict):
            continue
        model_id = config.get("model") or config.get("voice") or "default"
        settings = {
            key: value
            for key, value in config.items()
            if key not in {"type", "base_url", "api_key", "model"}
        }
        uow.providers.create(
            {
                "name": f"{capability_type.upper()} 默认渠道",
                "capability_type": capability_type,
                "adapter": config.get("type", capability_type),
                "base_url": config.get("base_url", ""),
                "api_key": config.get("api_key", ""),
                "settings": settings,
                "models": [
                    {
                        "name": model_id,
                        "model_id": model_id,
                        "capability_type": capability_type,
                        "capabilities": DEFAULT_CAPABILITIES.get(capability_type, {}),
                        "defaults": settings,
                    }
                ],
            }
        )
        count += 1
    if count:
        path.unlink()
    return count


def model_capabilities(uow) -> list[dict[str, Any]]:
    items = []
    for provider in uow.providers.list():
        for model in provider["models"]:
            items.append(
                {
                    **model,
                    "provider_profile_id": provider["id"],
                    "provider_name": provider["name"],
                    "adapter": provider["adapter"],
                    "enabled": provider["enabled"],
                }
            )
    return items


def _normalized_capability(value: Any) -> str:
    normalized = str(value or "llm").strip().lower()
    if normalized in {"", "text", "chat", "conversation", "custom"}:
        return "llm"
    return normalized


def provider_for_capability(uow, capability: str):
    """按模型级能力选择渠道；同一能力有全局默认模型时优先使用它。"""
    requested = _normalized_capability(capability)
    candidates: list[dict[str, Any]] = []
    for item in uow.providers.list():
        if not item["enabled"]:
            continue
        provider_capability = _normalized_capability(item.get("capability_type"))
        models = item.get("models") or []
        matches = [
            model
            for model in models
            if _normalized_capability(model.get("capability_type") or provider_capability) == requested
        ]
        if provider_capability == requested or matches:
            provider = uow.providers.get(item["id"], include_secret=True)
            provider["models"] = matches or provider.get("models", [])
            candidates.append(provider)
    if not candidates:
        raise RuntimeError(f"没有启用的 {capability} 渠道")
    for provider in candidates:
        default = [model for model in provider["models"] if model.get("is_default")]
        if default:
            provider["models"] = default + [
                model for model in provider["models"] if not model.get("is_default")
            ]
            return provider
    return candidates[0]
