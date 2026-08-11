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

export function regenerateArtifact(artifactId: string) {
    return post<Job>(
        `/api/artifacts/${seg(artifactId)}/regenerate`,
    );
}
