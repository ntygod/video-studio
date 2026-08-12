import pytest

from app.application.agent import durable_loop
from app.store import UnitOfWork


def _provider(app):
    with UnitOfWork(app.state.database) as uow:
        return uow.providers.create(
            {
                "name": "Checkpoint LLM",
                "capability_type": "llm",
                "adapter": "openai",
                "base_url": "https://example.invalid/v1",
                "api_key": "secret",
                "enabled": True,
                "settings": {},
                "models": [
                    {
                        "name": "Current default",
                        "model_id": "model-a",
                        "capability_type": "llm",
                        "capabilities": {},
                        "defaults": {},
                        "is_default": True,
                    },
                    {
                        "name": "Frozen model",
                        "model_id": "model-b",
                        "capability_type": "llm",
                        "capabilities": {},
                        "defaults": {},
                        "is_default": False,
                    },
                ],
            }
        )


def test_checkpoint_recovery_passes_the_frozen_model_explicitly(
    app,
    monkeypatch,
):
    provider = _provider(app)
    captured = {}
    sentinel = object()

    def fake_build_adapter(profile, model_id=None):
        captured["profile"] = profile
        captured["model_id"] = model_id
        return sentinel

    monkeypatch.setattr(
        durable_loop,
        "build_adapter",
        fake_build_adapter,
    )
    restored = durable_loop._adapter_for_checkpoint(
        app.state.database,
        {
            "provider_id": provider["id"],
            "model_id": "model-b",
        },
    )

    assert restored is sentinel
    assert captured["model_id"] == "model-b"
    assert captured["profile"]["models"][0]["model_id"] == "model-b"
    assert captured["profile"]["api_key"] == "secret"

    with pytest.raises(
        RuntimeError,
        match="model is no longer available",
    ):
        durable_loop._adapter_for_checkpoint(
            app.state.database,
            {
                "provider_id": provider["id"],
                "model_id": "deleted-model",
            },
        )


def test_live_agent_tokens_never_advertise_a_durable_cursor():
    events = []
    durable_loop._live_token(
        events.append,
        "turn-1",
        7,
        "片段",
    )

    assert events == [
        {
            "type": "token",
            "text": "片段",
            "durable": False,
            "turn_id": "turn-1",
            "token_index": 7,
        }
    ]
