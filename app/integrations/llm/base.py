from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol


class LLMConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatChunk:
    kind: Literal["token", "tool_call", "usage", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict[str, Any] | None = None


class LLMAdapter(Protocol):
    supports_native_tools: bool

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]: ...
