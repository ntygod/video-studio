"use client";

import { get, post, seg } from "./http";
import type { Job } from "./types";

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

export function regenerateArtifact(artifactId: string) {
    return post<Job>(
        `/api/artifacts/${seg(artifactId)}/regenerate`,
    );
}
