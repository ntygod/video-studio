from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from app.integrations.provider_http import provider_endpoint, provider_headers

from .base import ChatChunk, LLMConfigurationError, ToolCall, ToolSpec


class OpenAIAdapter:
    supports_native_tools = True

    def __init__(self, provider: dict[str, Any], model_id: str | None = None):
        self.provider = provider
        models = provider.get("models") or []
        if not models:
            raise LLMConfigurationError("LLM provider has no model profile")
        self.model = model_id or models[0]["model_id"]
        self.chat_url = provider_endpoint(provider, "chat/completions", "chat_path")
        self.headers = provider_headers(provider)

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"

        with httpx.stream(
            "POST",
            self.chat_url,
            headers=self.headers,
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            pending: dict[int, dict[str, str]] = {}
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    usage = event.get("usage")
                    if usage:
                        yield ChatChunk(kind="usage", usage=usage)
                    continue
                delta = (choices[0].get("delta") or {})
                if delta.get("content"):
                    yield ChatChunk(kind="token", text=delta["content"])
                for tool_call in delta.get("tool_calls") or []:
                    index = tool_call.get("index", 0)
                    slot = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tool_call.get("id"):
                        slot["id"] = tool_call["id"]
                    function = tool_call.get("function") or {}
                    if function.get("name"):
                        slot["name"] += function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]
            for index in sorted(pending):
                slot = pending[index]
                try:
                    arguments = json.loads(slot["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {"_raw": slot["arguments"]}
                yield ChatChunk(
                    kind="tool_call",
                    tool_call=ToolCall(
                        id=slot["id"] or f"call_{index}",
                        name=slot["name"],
                        arguments=arguments,
                    ),
                )
        yield ChatChunk(kind="done")
