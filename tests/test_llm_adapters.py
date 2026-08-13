# T1.1 LLM adapter fake-server tests.
# Verify token streaming, split tool-call argument accumulation,
# JSON protocol fallback, and fast failure on network errors.

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.integrations.llm import (
    JsonProtocolAdapter,
    LLMConfigurationError,
    OpenAIAdapter,
    ToolSpec,
    build_adapter,
)


class FakeHandler(BaseHTTPRequestHandler):
    responses = {}
    last_body = None

    def log_message(self, *args):
        pass

    def _send_sse(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for event in events:
            self.wfile.write(("data: " + event + chr(10) + chr(10)).encode())
        self.wfile.flush()

    def _send_json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) or b"{}"
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {}
        FakeHandler.last_body = parsed
        if self.path == "/chat/completions" and parsed.get("stream"):
            self._send_sse(self.responses.get("openai", []))
        elif self.path == "/chat/completions":
            self._send_json(self.responses.get("json", {}))
        else:
            self.send_error(404)


@pytest.fixture()
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=3)


@pytest.fixture()
def openai_events():
    return [
        json.dumps({"choices": [{"delta": {"content": "你好"}, "index": 0}]}),
        json.dumps({"choices": [{"delta": {"content": "，世界"}, "index": 0}]}),
        json.dumps({
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_unit", "arguments": "{\"unit_id\":\"u1\",\"path\":\""},
                            }
                        ]
                    }
                }
            ]
        }),
        json.dumps({
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": "第7章\"}"}}
                        ]
                    }
                }
            ]
        }),
        json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        json.dumps({"usage": {"prompt_tokens": 12, "completion_tokens": 34}}),
        "[DONE]",
    ]


def _provider(base_url, adapter):
    return {
        "adapter": adapter,
        "base_url": base_url,
        "api_key": "test-key",
        "models": [{"model_id": "fake-model", "name": "fake-model"}],
    }


def _collect(adapter, messages=None, tools=None):
    tokens = []
    calls = []
    usage = None
    done = False
    for chunk in adapter.stream(messages or [{"role": "user", "content": "hi"}], tools or []):
        if chunk.kind == "token":
            tokens.append(chunk.text)
        elif chunk.kind == "tool_call":
            calls.append(chunk.tool_call)
        elif chunk.kind == "usage":
            usage = chunk.usage
        elif chunk.kind == "done":
            done = True
    return tokens, calls, usage, done


def _json_message(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_openai_token_stream_and_tool_call(fake_server, openai_events):
    FakeHandler.responses["openai"] = openai_events
    adapter = OpenAIAdapter(_provider(f"http://127.0.0.1:{fake_server.server_port}", "openai"))
    tokens, calls, usage, done = _collect(adapter)
    assert "".join(tokens) == "你好，世界"
    assert len(calls) == 1
    assert calls[0].name == "read_unit"
    assert calls[0].arguments == {"unit_id": "u1", "path": "第7章"}
    assert usage is not None
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 34
    assert usage["_provider_request_id"] == ""
    assert usage["_provider_model_id"] == "fake-model"
    assert done


def test_build_adapter_falls_back_to_json_protocol():
    """只有 openai 走原生 tool calling，其余适配器一律回落 JSON 协议模拟。"""
    assert isinstance(build_adapter(_provider("http://x", "openai")), OpenAIAdapter)
    for adapter_name in ("grok2api", "edge", "custom", "anthropic", ""):
        adapter = build_adapter(_provider("http://x", adapter_name))
        assert isinstance(adapter, JsonProtocolAdapter), adapter_name


def test_openai_forwards_tool_result_messages(fake_server, openai_events):
    """回归防护：Agent 循环回填的 tool_calls / role=tool 消息必须原样送达。

    这条链路以前没有测试覆盖，导致适配器只在首轮（system+user）被验证过，
    而多轮回填的线格式不兼容问题一直藏着。
    """
    FakeHandler.responses["openai"] = openai_events
    FakeHandler.last_body = None
    adapter = OpenAIAdapter(_provider(f"http://127.0.0.1:{fake_server.server_port}", "openai"))
    messages = [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "读一下第7章"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_unit", "arguments": "{\"unit_id\":\"u1\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"unit\":{}}"},
    ]
    _collect(adapter, messages=messages, tools=[ToolSpec("read_unit", "读单元", {})])

    sent = FakeHandler.last_body["messages"]
    assert [message["role"] for message in sent] == ["system", "user", "assistant", "tool"]
    assert sent[2]["tool_calls"][0]["function"]["name"] == "read_unit"
    assert sent[3]["tool_call_id"] == "call_1"


def test_json_protocol_final(fake_server):
    FakeHandler.responses["json"] = _json_message({"final": "最终答复"})
    adapter = JsonProtocolAdapter(_provider(f"http://127.0.0.1:{fake_server.server_port}", "unknown"))
    tokens, calls, usage, done = _collect(adapter)
    assert "".join(tokens) == "最终答复"
    assert done


def test_json_protocol_tool_call(fake_server):
    FakeHandler.responses["json"] = _json_message({"tool": "list_units", "args": {"depth": 2}})
    adapter = JsonProtocolAdapter(_provider(f"http://127.0.0.1:{fake_server.server_port}", "unknown"))
    tokens, calls, usage, done = _collect(adapter, tools=[ToolSpec("list_units", "列单元", {})])
    assert len(calls) == 1
    assert calls[0].name == "list_units"
    assert calls[0].arguments == {"depth": 2}
    assert done


def test_disconnect_fails_fast():
    adapter = OpenAIAdapter(_provider("http://127.0.0.1:1", "openai"))
    start = time.monotonic()
    with pytest.raises(Exception):
        list(adapter.stream([{"role": "user", "content": "hi"}], []))
    assert time.monotonic() - start < 5


def test_missing_model_profile():
    with pytest.raises(LLMConfigurationError):
        OpenAIAdapter({"adapter": "openai", "base_url": "http://x", "models": []})
