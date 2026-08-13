import assert from "node:assert/strict";
import test from "node:test";

import {
    formatModelPricing,
    modelPricingForm,
    pricingFromModelForm,
} from "./model-pricing.ts";

test("model pricing round-trips between USD form and micro units", () => {
    const pricing = pricingFromModelForm({
        inputUsdPerMillion: "1.25",
        outputUsdPerMillion: "5",
        cachedInputUsdPerMillion: "0.25",
        requestUsd: "0.00001",
    });
    assert.deepEqual(pricing, {
        currency: "USD",
        input_microunits_per_million_tokens: 1_250_000,
        output_microunits_per_million_tokens: 5_000_000,
        cached_input_microunits_per_million_tokens: 250_000,
        request_microunits: 10,
    });
    assert.deepEqual(modelPricingForm(pricing), {
        inputUsdPerMillion: "1.25",
        outputUsdPerMillion: "5",
        cachedInputUsdPerMillion: "0.25",
        requestUsd: "0.00001",
    });
    assert.equal(
        formatModelPricing(pricing),
        "输入 $1.25/M · 输出 $5/M · 缓存 $0.25/M · 请求 $0.00001",
    );
});

test("empty price form stays explicitly unpriced", () => {
    assert.deepEqual(
        pricingFromModelForm({
            inputUsdPerMillion: "",
            outputUsdPerMillion: "",
            cachedInputUsdPerMillion: "",
            requestUsd: "",
        }),
        {},
    );
    assert.equal(formatModelPricing({}), "未定价");
});
