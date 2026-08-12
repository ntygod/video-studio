"use client";

import { get, post, seg } from "./http";
import { activeConversationTurnFromPlans } from "./runtime-policy-helpers";

export { activeConversationTurnFromPlans } from "./runtime-policy-helpers";

export type RuntimePolicyDecisionStatus =
    | "allowed"
    | "pending"
    | "approved"
    | "denied"
    | "expired";

export type RuntimePolicyDecision = {
    id: string;
    plan_id: string;
    task_id: string;
    action_key: string;
    action_type: string;
    risk_level: string;
    policy_version: string;
    status: RuntimePolicyDecisionStatus;
    reason: string;
    context: {
        turn_id?: string;
        step_id?: string;
        tool_name?: string;
        arguments?: Record<string, unknown>;
        [key: string]: unknown;
    };
    requested_by_type: string;
    requested_by_id: string;
    decided_by_type: string;
    decided_by_id: string;
    decision_note: string;
    created_at: number;
    updated_at: number;
    expires_at: number | null;
    decided_at: number | null;
};

export type RuntimePlanSummary = {
    id: string;
    project_id: string;
    kind: string;
    subject_type: string;
    subject_id: string;
    status: string;
    input: Record<string, unknown>;
    created_at?: number;
    updated_at?: number;
};

export type RuntimeProjectPolicyDecision = RuntimePolicyDecision & {
    plan: RuntimePlanSummary;
};

export type RuntimeBudgetState = {
    plan_id: string;
    budget: Record<string, number>;
    usage: {
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
        tool_calls: number;
        cost_microunits: number;
        wall_seconds: number;
    };
    violation: {
        dimension: string;
        limit: number;
        actual: number;
        message: string;
    } | null;
};

export function listTurnPolicyDecisions(
    turnId: string,
    status?: RuntimePolicyDecisionStatus,
) {
    return get<RuntimePolicyDecision[]>(
        `/api/turns/${seg(turnId)}/policy-decisions`,
        { status },
    );
}

export function listProjectPolicyDecisions(
    projectId: string,
    status: RuntimePolicyDecisionStatus = "pending",
    kind = "agent.turn",
    limit = 100,
) {
    return get<RuntimeProjectPolicyDecision[]>(
        `/api/projects/${seg(projectId)}/runtime-policy-decisions`,
        { status, kind, limit },
    );
}

export function approveRuntimePolicyDecision(
    decisionId: string,
    note = "",
) {
    return post<RuntimePolicyDecision>(
        `/api/runtime-policy-decisions/${seg(decisionId)}/approve`,
        { note },
    );
}

export function denyRuntimePolicyDecision(
    decisionId: string,
    note = "",
) {
    return post<RuntimePolicyDecision>(
        `/api/runtime-policy-decisions/${seg(decisionId)}/deny`,
        { note },
    );
}

export function getRuntimeBudget(planId: string) {
    return get<RuntimeBudgetState>(
        `/api/runtime-plans/${seg(planId)}/budget`,
    );
}

export async function getActiveConversationTurn(
    projectId: string,
    conversationId: string,
) {
    const plans = await get<RuntimePlanSummary[]>(
        `/api/projects/${seg(projectId)}/runtime-plans`,
        { kind: "agent.turn", limit: 100 },
    );
    return activeConversationTurnFromPlans(plans, conversationId);
}
