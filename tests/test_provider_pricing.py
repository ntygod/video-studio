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
