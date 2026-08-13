from app.domain.provider_pricing import (
    normalize_model_pricing,
    price_llm_usage,
)


def test_pricing_normalizes_usd_aliases_and_cached_tokens():
    pricing = normalize_model_pricing(
        {
            "input_usd_per_million_tokens": "1.25",
            "output_usd_per_million_tokens": 5,
            "cached_input_usd_per_million_tokens": "0.25",
            "request_usd": "0.000010",
        }
    )
    assert pricing == {
        "currency": "USD",
        "input_microunits_per_million_tokens": 1_250_000,
        "output_microunits_per_million_tokens": 5_000_000,
        "cached_input_microunits_per_million_tokens": 250_000,
        "request_microunits": 10,
    }
    result = price_llm_usage(
        pricing,
        {
            "prompt_tokens": 1_000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 400},
        },
    )
    assert result["breakdown"] == {
        "request_microunits": 10,
        "ordinary_prompt_tokens": 600,
        "ordinary_prompt_microunits": 750,
        "cached_prompt_tokens": 400,
        "cached_prompt_microunits": 100,
        "completion_tokens": 100,
        "completion_microunits": 500,
    }
    assert result["amount_microunits"] == 1_360


def test_token_pricing_without_provider_usage_is_marked_incomplete():
    result = price_llm_usage(
        {
            "input_usd_per_million_tokens": 1,
            "output_usd_per_million_tokens": 2,
            "request_usd": 0.001,
        },
        {"_provider_request_id": "missing-usage"},
    )
    assert result["priced"] is False
    # The known request fee is retained, while the call remains explicitly
    # incomplete because token usage was not reported.
    assert result["amount_microunits"] == 1_000
    assert result["usage"]["usage_reported"] is False


def test_provider_api_persists_canonical_model_pricing(client):
    response = client.post(
        "/api/provider-profiles",
        json={
            "name": "Priced LLM",
            "capability_type": "llm",
            "adapter": "openai",
            "base_url": "https://example.invalid/v1",
            "models": [
                {
                    "name": "Test",
                    "model_id": "test-priced-model",
                    "capability_type": "llm",
                    "pricing": {
                        "input_usd_per_million_tokens": 1,
                        "output_usd_per_million_tokens": 2,
                    },
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    model = response.json()["models"][0]
    assert model["pricing"] == {
        "currency": "USD",
        "input_microunits_per_million_tokens": 1_000_000,
        "output_microunits_per_million_tokens": 2_000_000,
    }
    assert model["pricing_updated_at"] is not None

    invalid = client.post(
        "/api/provider-profiles",
        json={
            "name": "Invalid price",
            "capability_type": "llm",
            "adapter": "openai",
            "base_url": "https://example.invalid/v1",
            "models": [
                {
                    "model_id": "bad-price",
                    "pricing": {
                        "input_usd_per_million_tokens": -1,
                    },
                }
            ],
        },
    )
    assert invalid.status_code == 422


def test_agent_pricing_snapshot_survives_later_provider_price_change(
    app,
    client,
):
    from app.application.agent.runtime_cost_metering import (
        _load_provider_and_snapshot,
    )

    created = client.post(
        "/api/provider-profiles",
        json={
            "name": "Frozen price",
            "capability_type": "llm",
            "adapter": "openai",
            "base_url": "https://example.invalid/v1",
            "models": [
                {
                    "name": "Frozen",
                    "model_id": "frozen-model",
                    "capability_type": "llm",
                    "pricing": {
                        "input_usd_per_million_tokens": 1,
                        "output_usd_per_million_tokens": 2,
                    },
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    provider = created.json()
    checkpoint = {
        "provider_id": provider["id"],
        "model_id": "frozen-model",
        "round": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    _provider, first = _load_provider_and_snapshot(
        app.state.database,
        checkpoint,
    )
    assert first["pricing"][
        "input_microunits_per_million_tokens"
    ] == 1_000_000

    patched = client.patch(
        f"/api/provider-profiles/{provider['id']}",
        json={
            "models": [
                {
                    "name": "Frozen",
                    "model_id": "frozen-model",
                    "capability_type": "llm",
                    "pricing": {
                        "input_usd_per_million_tokens": 9,
                        "output_usd_per_million_tokens": 10,
                    },
                }
            ]
        },
    )
    assert patched.status_code == 200, patched.text
    _provider, restored = _load_provider_and_snapshot(
        app.state.database,
        checkpoint,
    )
    assert restored == first
    assert restored["pricing"][
        "input_microunits_per_million_tokens"
    ] == 1_000_000
