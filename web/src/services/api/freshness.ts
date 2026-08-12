"use client";

import { get, post, seg } from "./http";
import type { Asset, Job } from "./types";

export type ArtifactFreshnessStatus =
    | "fresh"
    | "stale"
    | "blocked"
    | "needs_review";

export type ArtifactFreshness = {
    artifact_id: string;
    project_id: string;
    status: ArtifactFreshnessStatus;
    reason: string;
    stale_from_version_ids: string[];
    blocked_by_asset_ids: string[];
    detected_at: number | null;
    updated_at: number;
};

export type ProjectArtifactFreshnessItem = ArtifactFreshness & {
    unit_id: string | null;
    kind: string;
    name: string;
    current_version_id: string | null;
};

export type ArtifactFreshnessCounts = Record<
    ArtifactFreshnessStatus,
    number
>;

export type ProjectArtifactFreshness = {
    counts: ArtifactFreshnessCounts;
    items: ProjectArtifactFreshnessItem[];
};

export type ArtifactDependency = {
    id: string;
    project_id: string;
    upstream_version_id: string;
    downstream_artifact_id: string;
    downstream_version_id: string;
    dependency_type: string;
    metadata: Record<string, unknown>;
    created_at: number;
};

export type AssetDependencyInput = {
    id: string;
    project_id: string;
    upstream_asset_id: string;
    upstream_asset: Partial<Asset> & { id: string };
    asset_exists: boolean;
    downstream_artifact_id: string;
    downstream_version_id: string;
    dependency_type: string;
    metadata: Record<string, unknown>;
    created_at: number;
};

export type ArtifactImpactItem = {
    artifact_id: string;
    artifact_kind: string;
    artifact_name: string;
    dependency: ArtifactDependency;
    freshness: ArtifactFreshness;
};

export type RegenerationPreviewAction =
    | "none"
    | "regenerate_llm"
    | "recompile_timeline"
    | "repair_timeline_assets"
    | "review"
    | "manual";

export type RegenerationPreviewExecutionState =
    | "ready"
    | "waiting_for_predecessors"
    | "requires_input"
    | "requires_review"
    | "manual"
    | "blocked"
    | "skipped";

export type RegenerationPreviewBlocker = {
    code: string;
    message: string;
    entity_type?: string;
    entity_id?: string;
};

export type RegenerationPreviewStep = {
    artifact_id: string;
    artifact_kind: string;
    artifact_name: string;
    unit_id: string | null;
    current_version_id: string | null;
    expected_current_version_id: string | null;
    freshness: ArtifactFreshness;
    action: RegenerationPreviewAction;
    execution_state: RegenerationPreviewExecutionState;
    depends_on: string[];
    external_upstream_artifact_ids: string[];
    missing_asset_ids: string[];
    direct_missing_asset_ids: string[];
    source_job_id: string | null;
    blockers: RegenerationPreviewBlocker[];
    can_execute_automatically: boolean;
    available_after_plan: boolean;
};

export type RegenerationPreviewSummary = {
    total: number;
    automatable: number;
    ready: number;
    waiting_for_predecessors: number;
    requires_input: number;
    requires_review: number;
    manual: number;
    blocked: number;
    skipped: number;
};

export type RegenerationCascadePreview = {
    project_id: string;
    root_artifact_ids: string[];
    include_downstream: boolean;
    order: string[];
    summary: RegenerationPreviewSummary;
    steps: RegenerationPreviewStep[];
};

export type RegenerationPreviewInput = {
    artifact_ids: string[];
    include_downstream?: boolean;
    /** Stable for retries of one create intent; ignored by preview. */
    client_token?: string;
};

export type RegenerationPlanStatus =
    | "draft"
    | "running"
    | "blocked"
    | "succeeded"
    | "failed"
    | "canceled";

export type RegenerationPlanStepStatus =
    | RegenerationPreviewExecutionState
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "canceled";

export type RegenerationPlanStepAttempt = {
    attempt: number;
    status: string;
    job_id: string | null;
    source_job_id: string | null;
    input: Record<string, unknown>;
    result: Record<string, unknown>;
    blockers: RegenerationPreviewBlocker[];
    error: string;
    started_at: number | null;
    completed_at: number | null;
    recorded_at: number;
};

export type RegenerationPlanStep = {
    id: string;
    plan_id: string;
    project_id: string;
    artifact_id: string;
    order_index: number;
    artifact_kind: string;
    artifact_name: string;
    unit_id: string | null;
    expected_version_id: string | null;
    action: RegenerationPreviewAction;
    status: RegenerationPlanStepStatus;
    execution_attempt: number;
    attempt_history: RegenerationPlanStepAttempt[];
    can_execute_automatically: boolean;
    depends_on_artifact_ids: string[];
    external_upstream_artifact_ids: string[];
    blockers: RegenerationPreviewBlocker[];
    missing_asset_ids: string[];
    direct_missing_asset_ids: string[];
    source_job_id: string | null;
    job_id: string | null;
    claimed: boolean;
    claim_owner: string;
    claim_until: number | null;
    claim_attempt: number;
    input: {
        replacements?: Record<string, string>;
        [key: string]: unknown;
    };
    result: Record<string, unknown>;
    error: string;
    created_at: number;
    updated_at: number;
    started_at: number | null;
    completed_at: number | null;
};

export type RegenerationPlanSummary = {
    total?: number;
    automatable?: number;
    completed?: number;
    failed?: number;
    canceled?: number;
    claimed?: number;
    statuses?: Record<string, number>;
    [key: string]: unknown;
};

export type RegenerationPlan = {
    id: string;
    project_id: string;
    status: RegenerationPlanStatus;
    execution_attempt: number;
    root_artifact_ids: string[];
    include_downstream: boolean;
    snapshot_sha256: string;
    summary: RegenerationPlanSummary;
    error: string;
    created_at: number;
    updated_at: number;
    started_at: number | null;
    completed_at: number | null;
    steps?: RegenerationPlanStep[];
};

export function getProjectArtifactFreshness(
    projectId: string,
    includeFresh = false,
) {
    return get<ProjectArtifactFreshness>(
        `/api/projects/${seg(projectId)}/artifact-freshness`,
        { include_fresh: includeFresh },
    );
}

export function getArtifactImpact(artifactId: string) {
    return get<ArtifactImpactItem[]>(
        `/api/artifacts/${seg(artifactId)}/impact`,
    );
}

export function getArtifactAssetDependencies(artifactId: string) {
    return get<AssetDependencyInput[]>(
        `/api/artifacts/${seg(artifactId)}/asset-dependencies`,
    );
}

export function previewRegenerationCascade(
    projectId: string,
    input: RegenerationPreviewInput,
) {
    return post<RegenerationCascadePreview>(
        `/api/projects/${seg(projectId)}/artifact-regeneration/preview`,
        {
            artifact_ids: input.artifact_ids,
            include_downstream: input.include_downstream ?? true,
        },
    );
}

export function createRegenerationPlan(
    projectId: string,
    input: RegenerationPreviewInput,
) {
    return post<RegenerationPlan>(
        `/api/projects/${seg(projectId)}/artifact-regeneration/plans`,
        {
            artifact_ids: input.artifact_ids,
            include_downstream: input.include_downstream ?? true,
            client_token: input.client_token,
        },
    );
}

export function listRegenerationPlans(
    projectId: string,
    limit = 100,
) {
    return get<RegenerationPlan[]>(
        `/api/projects/${seg(projectId)}/artifact-regeneration/plans`,
        { limit },
    );
}

export function getRegenerationPlan(planId: string) {
    return get<RegenerationPlan>(
        `/api/artifact-regeneration/plans/${seg(planId)}`,
    );
}

export function startRegenerationPlan(planId: string) {
    return post<RegenerationPlan>(
        `/api/artifact-regeneration/plans/${seg(planId)}/start`,
    );
}

export function retryRegenerationPlan(
    planId: string,
    expectedExecutionAttempt: number,
) {
    return post<RegenerationPlan>(
        `/api/artifact-regeneration/plans/${seg(planId)}/retry`,
        { expected_execution_attempt: expectedExecutionAttempt },
    );
}

export function cancelRegenerationPlan(planId: string) {
    return post<RegenerationPlan>(
        `/api/artifact-regeneration/plans/${seg(planId)}/cancel`,
    );
}

export function setRegenerationPlanStepInput(
    stepId: string,
    replacements: Record<string, string>,
) {
    return post<RegenerationPlan>(
        `/api/artifact-regeneration/steps/${seg(stepId)}/input`,
        { replacements },
    );
}

export function regenerateArtifact(artifactId: string) {
    return post<Job>(
        `/api/artifacts/${seg(artifactId)}/regenerate`,
    );
}
