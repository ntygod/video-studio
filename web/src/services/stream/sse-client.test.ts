import assert from "node:assert/strict";
import test from "node:test";

import { durableStreamCursor } from "./sse-client.ts";


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
