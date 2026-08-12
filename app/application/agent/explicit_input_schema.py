"""Expose exact production-input fields to the Agent planner."""

from __future__ import annotations

from typing import Any

from .tools import TOOL_BY_NAME


def _array(description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": 500,
        "items": {"type": "string"},
        "description": description,
    }


EXPLICIT_INPUT_PROPERTIES = {
    "input_version_ids": _array(
        "直接指定不可变 ArtifactVersion ID；只在确实读取了该版本时填写"
    ),
    "input_artifact_ids": _array(
        "直接指定 Artifact ID；系统在提交时冻结它的当前版本"
    ),
    "input_asset_ids": _array(
        "直接指定生成时实际使用的 Asset ID"
    ),
}


def install_explicit_input_schema() -> None:
    for tool_name in ("write_artifact", "generate_media"):
        tool = TOOL_BY_NAME.get(tool_name)
        if tool is None:
            raise RuntimeError(
                f"Agent production tool is not registered: {tool_name}"
            )
        properties = tool.spec.parameters.setdefault(
            "properties",
            {},
        )
        properties.update(EXPLICIT_INPUT_PROPERTIES)


__all__ = [
    "EXPLICIT_INPUT_PROPERTIES",
    "install_explicit_input_schema",
]
