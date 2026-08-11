from __future__ import annotations

from typing import Any

from .base import (
    ChatChunk,
    LLMAdapter,
    LLMConfigurationError,
    ToolCall,
    ToolSpec,
)
from .json_protocol import JsonProtocolAdapter, extract_json
from .openai_adapter import OpenAIAdapter


def _pick_llm_model(provider: dict[str, Any]) -> str:
    """多能力渠道里优先选择 llm 模型；有全局默认标记时直接用它。"""
    models = provider.get("models") or []
    fallback = str(provider.get("capability_type") or "llm").lower()
    for model in models:
        if model.get("is_default"):
            return str(model["model_id"])
    for model in models:
        capability = str(model.get("capability_type") or fallback).lower()
        if capability in ("llm", "text", "chat"):
            return str(model["model_id"])
    return str(models[0]["model_id"]) if models else ""


def build_adapter(provider: dict[str, Any], model_id: str | None = None) -> LLMAdapter:
    """按 provider.adapter 选择适配器。

    只有显式声明为 OpenAI 兼容协议的渠道才走原生 tool calling；空值和其他
    adapter 一律回落到 JSON 协议模拟，避免未知渠道被误当成 OpenAI。
    """
    model_id = model_id or _pick_llm_model(provider)
    adapter = str(provider.get("adapter") or "").strip().lower()
    if adapter == "openai":
        return OpenAIAdapter(provider, model_id=model_id)
    return JsonProtocolAdapter(provider, model_id=model_id)


class LLMClient:
    """兼容旧调用方的非流式包装；Job 引擎与旧代码仍可使用。"""

    def __init__(self, provider: dict[str, Any], model_id: str | None = None):
        if model_id:
            self._adapter = build_adapter(provider, model_id=model_id)
        else:
            self._adapter = build_adapter(provider)

    def chat(self, messages: list[dict[str, Any]], max_tokens: int = 8000) -> str:
        parts: list[str] = []
        for chunk in self._adapter.stream(messages, [], max_tokens=max_tokens):
            if chunk.kind == "token":
                parts.append(chunk.text)
        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("LLM returned empty content")
        return text

    def chat_json(self, messages: list[dict[str, Any]], max_tokens: int = 8000) -> dict[str, Any]:
        text = self.chat(messages, max_tokens=max_tokens)
        try:
            return extract_json(text)
        except Exception:
            # JSON 协议回退适配器只把内层 final 文本作为 token 流出，此时按 final 包裹。
            return {"final": text}


__all__ = [
    "ChatChunk",
    "JsonProtocolAdapter",
    "LLMAdapter",
    "LLMClient",
    "LLMConfigurationError",
    "OpenAIAdapter",
    "ToolCall",
    "ToolSpec",
    "build_adapter",
    "extract_json",
]
