import assert from "node:assert/strict";
import test from "node:test";

import {
    advanceDurableStreamCursor,
    durableStreamCursor,
} from "./sse-client.ts";


test("durable stream cursor ignores live token identifiers", () => {
    assert.equal(
        durableStreamCursor({
            id: "turn-1:live:7",
            type: "token",
            durable: false,
        }),
        null,
    );
    assert.equal(
        durableStreamCursor({
            id: "turn-1:12",
            type: "step.done",
        }),
        "turn-1:12",
    );
    assert.equal(
        durableStreamCursor({ type: "token", durable: false }),
        null,
    );
});


test("durable stream cursor never moves backward on replay", () => {
    assert.equal(
        advanceDurableStreamCursor("", {
            id: "turn-1:7",
            type: "step.start",
        }),
        "turn-1:7",
    );
    assert.equal(
        advanceDurableStreamCursor("turn-1:12", {
            id: "turn-1:7",
            type: "step.start",
        }),
        "turn-1:12",
    );
    assert.equal(
        advanceDurableStreamCursor("turn-1:12", {
            id: "turn-1:13",
            type: "step.done",
        }),
        "turn-1:13",
    );
    assert.equal(
        advanceDurableStreamCursor("turn-1:13", {
            id: "turn-1:live:8",
            type: "token",
            durable: false,
        }),
        "turn-1:13",
    );
});
