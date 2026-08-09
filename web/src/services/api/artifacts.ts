"use client";

import { get, post, seg } from "./http";
import type { Artifact, ArtifactVersion, Proposal } from "./types";

export function listArtifacts(projectId: string, unitId?: string) {
    return get<Artifact[]>(`/api/projects/${seg(projectId)}/artifacts`, { unit_id: unitId });
}

export type ArtifactCreateInput = {
    unit_id?: string | null;
    kind: string;
    name: string;
    schema_id?: string;
    payload?: Record<string, unknown>;
};

export function createArtifact(projectId: string, input: ArtifactCreateInput) {
    return post<Artifact>(`/api/projects/${seg(projectId)}/artifacts`, input);
}

/** 追加一个新版本。后端只追加不覆盖，历史版本永久保留。 */
export function addArtifactVersion(artifactId: string, payload: Record<string, unknown>, note = "") {
    return post<ArtifactVersion>(`/api/artifacts/${seg(artifactId)}/versions`, { payload, note });
}

export function approveArtifactVersion(versionId: string) {
    return post<ArtifactVersion>(`/api/artifact-versions/${seg(versionId)}/approve`);
}

export function lockArtifactVersion(versionId: string) {
    return post<ArtifactVersion>(`/api/artifact-versions/${seg(versionId)}/lock`);
}

export type AcceptProposalResult = {
    proposal: Proposal;
    artifact_id: string;
    version: ArtifactVersion;
};

/** 采纳提案，生成一个新的 artifact 版本。 */
export function acceptProposal(proposalId: string) {
    return post<AcceptProposalResult>(`/api/proposals/${seg(proposalId)}/accept`);
}

export function rejectProposal(proposalId: string) {
    return post<Proposal>(`/api/proposals/${seg(proposalId)}/reject`);
}
