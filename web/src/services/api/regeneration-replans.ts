"use client";

import { get, post, seg } from "./http";
import type {
    RegenerationPlan,
    RegenerationPlanStatus,
} from "./freshness";

export type RegenerationReplanSourceStatus = Extract<
    RegenerationPlanStatus,
    "draft" | "blocked" | "failed" | "canceled"
>;

export type RegenerationPlanReplanRelation = {
    id: string;
    project_id: string;
    source_plan_id: string;
    target_plan_id: string;
    source_status: RegenerationReplanSourceStatus;
    source_execution_attempt: number;
    target_snapshot_sha256: string;
    reason: string;
    created_at: number;
};

export type RegenerationPlanLineage = {
    plan_id: string;
    project_id: string;
    replanned_from: RegenerationPlanReplanRelation | null;
    replanned_by: RegenerationPlanReplanRelation | null;
};

export type ReplanRegenerationPlanInput = {
    expected_source_status: RegenerationReplanSourceStatus;
    expected_execution_attempt: number;
    reason?: string;
    client_token?: string;
};

export function getRegenerationPlanLineage(planId: string) {
    return get<RegenerationPlanLineage>(
        `/api/artifact-regeneration/plans/${seg(planId)}/lineage`,
    );
}

export function replanRegenerationPlan(
    planId: string,
    input: ReplanRegenerationPlanInput,
) {
    return post<RegenerationPlan>(
        `/api/artifact-regeneration/plans/${seg(planId)}/replan`,
        input,
    );
}
