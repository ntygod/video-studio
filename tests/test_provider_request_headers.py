from app.integrations.llm.openai_adapter import OpenAIAdapter
from app.integrations.provider_request import (
    bind_provider_request,
    reset_provider_request,
)


class FakeStreamResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(["data: [DONE]"])


def test_openai_adapter_injects_dynamic_idempotency_header(monkeypatch):
    captured = {}

    def fake_stream(_method, _url, *, headers, json, timeout):
        captured["headers"] = dict(headers)
        captured["json"] = dict(json)
        assert timeout == 120
        return FakeStreamResponse()

    monkeypatch.setattr(
        "app.integrations.llm.openai_adapter.httpx.stream",
        fake_stream,
    )
    provider = {
        "adapter": "openai",
        "base_url": "https://provider.example/v1",
        "api_key": "secret",
        "settings": {},
        "models": [{"model_id": "model-1"}],
    }
    token = bind_provider_request(
        request_id="request-1",
        idempotency_key="video-studio-key",
        idempotency_header="Idempotency-Key",
    )
    try:
        chunks = list(OpenAIAdapter(provider).stream([], []))
    finally:
        reset_provider_request(token)
    assert captured["headers"]["Idempotency-Key"] == "video-studio-key"
    assert [chunk.kind for chunk in chunks] == ["usage", "done"]
