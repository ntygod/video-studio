export type ActiveRuntimePlan = {
    status: string;
    subject_type: string;
    subject_id: string;
    input: Record<string, unknown>;
};

/** Select the durable Agent Turn that still owns one conversation. */
export function activeConversationTurnFromPlans(
    plans: ActiveRuntimePlan[],
    conversationId: string,
): string | null {
    const active = plans.find(
        (plan) =>
            ["queued", "running"].includes(plan.status) &&
            plan.subject_type === "agent_turn" &&
            plan.input.conversation_id === conversationId,
    );
    return active?.subject_id || null;
}
