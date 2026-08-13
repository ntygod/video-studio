import assert from "node:assert/strict";
import test from "node:test";

import {
    normalizeUnpricedProviderMode,
    runtimeCostPolicyMeta,
} from "./runtime-cost-policy-helpers.ts";

test("unknown Provider cost modes remain backward-compatible", () => {
    assert.equal(normalizeUnpricedProviderMode(undefined), "allow");
    assert.equal(normalizeUnpricedProviderMode("legacy"), "allow");
    assert.equal(normalizeUnpricedProviderMode("block"), "block");
});

test("strict Provider cost policy explains both enforcement boundaries", () => {
    const meta = runtimeCostPolicyMeta("block");
    assert.equal(meta.shortLabel, "严格");
    assert.match(meta.warning, /请求前/);
    assert.match(meta.warning, /usage/);
});
