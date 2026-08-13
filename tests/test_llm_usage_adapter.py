import json as jsonlib

from app.integrations.llm.openai_adapter import OpenAIAdapter


class FakeStreamResponse:
    def __init__(self, status_code, lines=()):
        self.status_code = status_code
        self._lines = list(lines)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(
                f"unexpected HTTP status {self.status_code}"
            )

    def iter_lines(self):
        return iter(self._lines)


def _provider():
    return {
        "name": "Compatible",
        "adapter": "openai",
        "base_url": "https://provider.example/v1",
        "api_key": "",
        "settings": {},
        "models": [{"model_id": "compatible-model"}],
    }


def test_openai_adapter_retries_without_stream_options_when_gateway_rejects_it(
    monkeypatch,
):
    requests = []

    def fake_stream(
        _method,
        _url,
        *,
        headers,
        json,
        timeout,
    ):
        assert headers == {}
        assert timeout == 120
        requests.append(jsonlib.loads(jsonlib.dumps(json)))
        if len(requests) == 1:
            return FakeStreamResponse(400)
        return FakeStreamResponse(
            200,
            [
                'data: {"id":"response-1","model":"compatible-model","choices":[{"delta":{"content":"ok"}}]}',
                'data: {"id":"response-1","model":"compatible-model","choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
                "data: [DONE]",
            ],
        )

    monkeypatch.setattr(
        "app.integrations.llm.openai_adapter.httpx.stream",
        fake_stream,
    )
    chunks = list(OpenAIAdapter(_provider()).stream([], []))

    assert len(requests) == 2
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert "stream_options" not in requests[1]
    assert [chunk.kind for chunk in chunks] == ["token", "usage", "done"]
    assert chunks[0].text == "ok"
    assert chunks[1].usage["prompt_tokens"] == 3
    assert chunks[1].usage["completion_tokens"] == 2
    assert chunks[1].usage["_provider_request_id"] == "response-1"
