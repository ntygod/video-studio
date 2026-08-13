"use client";

import { get, patch, post, seg } from "./http";
import { activeConversationTurnFromPlans } from "./runtime-policy-helpers";
import type { UnpricedProviderMode } from "./runtime-cost-policy-helpers";

export { activeConversationTurnFromPlans } from "./runtime-policy-helpers";
export {
    normalizeUnpricedProviderMode,
    runtimeCostPolicyMeta,
} from "./runtime-cost-policy-helpers";
export type { UnpricedProviderMode } from "./runtime-cost-policy-helpers";

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

export type ProjectRuntimeCostPolicyState = {
    project_id: string;
    revision: number;
    policy: {
        unpriced_provider_mode: UnpricedProviderMode;
    };
};

export type RuntimeBudgetState = {
    plan_id: string;
    plan_status: string;
    budget: Record<string, number> & {
        max_cost_microunits?: number;
        max_cost_usd?: number;
    };
    usage: {
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
        tool_calls: number;
        cost_microunits: number;
        cost_usd: number;
        provider_calls: number;
        priced_calls: number;
        unpriced_calls: number;
        wall_seconds: number;
    };
    violation: {
        dimension: string;
        limit: number;
        actual: number;
        limit_usd?: number;
        actual_usd?: number;
        message: string;
    } | null;
};

export type RuntimeCostEntry = {
    id: string;
    plan_id: string;
    task_id: string;
    attempt_id: string | null;
    usage_key: string;
    source_type: string;
    provider_profile_id: string;
    provider_name: string;
    adapter: string;
    model_profile_id: string;
    model_id: string;
    capability_type: string;
    provider_request_id: string;
    currency: string;
    pricing_sha256: string;
    pricing_snapshot: Record<string, unknown>;
    usage: {
        prompt_tokens: number;
        completion_tokens: number;
        cached_prompt_tokens: number;
        total_tokens: number;
        usage_reported: boolean;
        provider_request_id: string;
        provider_model_id: string;
        [key: string]: unknown;
    };
    breakdown: Record<string, number>;
    amount_microunits: number;
    amount_usd: number;
    priced: boolean;
    created_at: number;
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

export function getProjectRuntimeCostPolicy(projectId: string) {
    return get<ProjectRuntimeCostPolicyState>(
        `/api/projects/${seg(projectId)}/runtime-cost-policy`,
    );
}

export function patchProjectRuntimeCostPolicy(
    projectId: string,
    input: {
        expected_revision: number;
        unpriced_provider_mode: UnpricedProviderMode;
    },
) {
    return patch<ProjectRuntimeCostPolicyState>(
        `/api/projects/${seg(projectId)}/runtime-cost-policy`,
        input,
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

export function listRuntimeCosts(planId: string, limit = 100) {
    return get<RuntimeCostEntry[]>(
        `/api/runtime-plans/${seg(planId)}/costs`,
        { limit },
    );
}

export function getTurnRuntimeBudget(turnId: string) {
    return get<RuntimeBudgetState>(
        `/api/turns/${seg(turnId)}/budget`,
    );
}

export function listTurnRuntimeCosts(turnId: string, limit = 20) {
    return get<RuntimeCostEntry[]>(
        `/api/turns/${seg(turnId)}/costs`,
        { limit },
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
