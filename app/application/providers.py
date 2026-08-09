import json
from pathlib import Path
from typing import Any


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

