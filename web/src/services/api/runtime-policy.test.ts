import assert from "node:assert/strict";
import test from "node:test";

import {
    activeConversationTurnFromPlans,
    type ActiveRuntimePlan,
} from "./runtime-policy-helpers.ts";

function plan(
    id: string,
    status: string,
    conversationId: string,
    turnId: string,
): ActiveRuntimePlan & { id: string } {
    return {
        id,
        status,
        subject_type: "agent_turn",
        subject_id: turnId,
        input: { conversation_id: conversationId },
    };
}

test("active conversation turn ignores terminal plans", () => {
    const plans = [
        plan("failed", "failed", "conversation-1", "turn-failed"),
        plan("running", "running", "conversation-1", "turn-running"),
    ];
    assert.equal(
        activeConversationTurnFromPlans(plans, "conversation-1"),
        "turn-running",
    );
});

test("active conversation turn remains scoped to one conversation", () => {
    const plans = [
        plan("other", "running", "conversation-2", "turn-other"),
    ];
    assert.equal(
        activeConversationTurnFromPlans(plans, "conversation-1"),
        null,
    );
});
