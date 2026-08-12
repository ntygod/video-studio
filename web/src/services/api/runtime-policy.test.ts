import assert from "node:assert/strict";
import test from "node:test";

import {
    activeConversationTurnFromPlans,
    type RuntimePlanSummary,
} from "./runtime-policy.ts";

function plan(
    id: string,
    status: string,
    conversationId: string,
    turnId: string,
): RuntimePlanSummary {
    return {
        id,
        project_id: "project-1",
        kind: "agent.turn",
        subject_type: "agent_turn",
        subject_id: turnId,
        status,
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
