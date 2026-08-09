import json
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class LLMConfigurationError(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
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


class LLMClient:
    def __init__(self, provider: dict[str, Any]):
        self.provider = provider
        models = provider.get("models") or []
        if not models:
            raise LLMConfigurationError("LLM provider has no model profile")
        self.model = models[0]["model_id"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5), reraise=True)
    def chat(self, messages: list[dict[str, str]], max_tokens: int = 8000) -> str:
        adapter = self.provider.get("adapter", "openai")
        base_url = str(self.provider.get("base_url") or "").rstrip("/")
        api_key = self.provider.get("api_key") or ""
        if adapter == "anthropic":
            system = "\n\n".join(
                message["content"] for message in messages if message["role"] == "system"
            )
            body_messages = [message for message in messages if message["role"] != "system"]
            response = httpx.post(
                base_url + "/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "system": system,
                    "messages": body_messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
                timeout=600,
            )
            response.raise_for_status()
            content = "".join(
                block.get("text", "")
                for block in response.json().get("content", [])
                if block.get("type") == "text"
            )
        else:
            response = httpx.post(
                base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": max_tokens,
                },
                timeout=600,
            )
            response.raise_for_status()
            content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if not str(content).strip():
            raise RuntimeError("LLM returned empty content")
        return str(content)

    def chat_json(self, messages: list[dict[str, str]], max_tokens: int = 8000) -> dict[str, Any]:
        last_error = None
        repair_messages = list(messages)
        for _ in range(3):
            text = self.chat(repair_messages, max_tokens=max_tokens)
            try:
                return extract_json(text)
            except Exception as exc:
                last_error = exc
                repair_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": (
                            "上一次响应不是完整合法的 JSON。请重新输出一个完整 JSON 对象，"
                            f"不要 Markdown 和解释。解析错误：{exc}"
                        ),
                    }
                ]
        raise RuntimeError(f"LLM structured output failed: {last_error}")

