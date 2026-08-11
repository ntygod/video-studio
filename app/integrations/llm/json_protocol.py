from __future__ import annotations

import json
import re
from typing import Any, Iterator

import httpx

from app.integrations.provider_http import provider_endpoint, provider_headers

from .base import ChatChunk, LLMConfigurationError, ToolCall, ToolSpec


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取第一个合法 JSON 对象。"""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.S)
    if fence:
        stripped = fence.group(1)
    else:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("LLM structured response must be a JSON object")
    return value


def _tool_prompt(tools: list[ToolSpec]) -> str:
    lines = [
        '你可以调用以下工具（只输出一行合法 JSON，不要 Markdown、不要解释）：',
        '',
        '调用工具格式：{"tool":"工具名","args":{...}}',
        '直接回答格式：{"final":"你的回复文本"}',
        '',
        '可用工具：',
    ]
    for tool in tools:
        lines.append(
            f"- {tool.name}: {tool.description}\n"
            "  参数 JSON Schema: "
            + json.dumps(tool.parameters, ensure_ascii=False)
        )
    return "\n".join(lines)


class JsonProtocolAdapter:
    """不支持原生 tool call 时的回退：工具渲染进 system prompt，逐条解析 JSON 输出。"""

    supports_native_tools = False

    def __init__(self, provider: dict[str, Any], model_id: str | None = None):
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
        body_messages = list(messages)
        if tools:
            body_messages = [
                {"role": "system", "content": _tool_prompt(tools)}
            ] + [
                message
                for message in body_messages
                if message.get("role") != "system"
            ]
        response = httpx.post(
            self.chat_url,
            headers=self.headers,
            json={
                "model": self.model,
                "messages": body_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if not str(content).strip():
            raise RuntimeError("LLM returned empty content")
        parsed = extract_json(str(content))
        if "tool" in parsed:
            arguments = parsed.get("args") or {}
            if not isinstance(arguments, dict):
                raise ValueError("tool args must be an object")
            yield ChatChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id="json-fallback",
                    name=str(parsed["tool"]),
                    arguments=arguments,
                ),
            )
        elif "final" in parsed:
            yield ChatChunk(kind="token", text=str(parsed["final"]))
        else:
            yield ChatChunk(kind="token", text=json.dumps(parsed, ensure_ascii=False))
        yield ChatChunk(kind="usage", usage={})
        yield ChatChunk(kind="done")
