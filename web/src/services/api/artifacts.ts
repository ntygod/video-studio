"use client";

import { get, post, seg } from "./http";
import type { Artifact, ArtifactVersion, Page, Proposal } from "./types";

export function listArtifactsPage(
    projectId: string,
    params: {
        unit_id?: string | null;
        kind?: string | null;
        include_payload?: boolean;
        limit?: number;
        cursor?: string | null;
    } = {},
) {
    return get<Page<Artifact>>(`/api/projects/${seg(projectId)}/artifacts`, params);
}

/** 稿件列表（分页行走）。默认不带正文，列表场景用；画布需要正文时传 includePayload。 */
export async function listArtifacts(
    projectId: string,
    unitId?: string,
    includePayload = false,
): Promise<Artifact[]> {
    const items: Artifact[] = [];
    let cursor: string | null = null;
    do {
        const page = await listArtifactsPage(projectId, {
            unit_id: unitId,
            include_payload: includePayload,
            limit: 50,
            cursor,
        });
        items.push(...page.items);
        cursor = page.next_cursor;
    } while (cursor);
    return items;
}

/** 待处理提案列表（分页行走）。 */
export async function listProposals(projectId: string, status?: string): Promise<Proposal[]> {
    const items: Proposal[] = [];
    let cursor: string | null = null;
    do {
        const page: Page<Proposal> = await get(`/api/projects/${seg(projectId)}/proposals`, {
            status,
            limit: 50,
            cursor,
        });
        items.push(...page.items);
        cursor = page.next_cursor;
    } while (cursor);
    return items;
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

export function listArtifactVersions(artifactId: string) {
    return get<ArtifactVersion[]>(`/api/artifacts/${seg(artifactId)}/versions`);
}

/** 结构化版本 diff（T4.3）。 */
export type VersionDiff = {
    version_a: { id: string; version: number };
    version_b: { id: string; version: number };
    field_diffs: ProposalFieldDiff[];
};

export function diffArtifactVersions(versionA: string, versionB: string) {
    return get<VersionDiff>(`/api/artifact-versions/${seg(versionA)}/diff/${seg(versionB)}`);
}

/** 回滚到目标版本：追加新版本而非覆盖历史（T4.3）。 */
export function restoreArtifactVersion(artifactId: string, versionId: string) {
    return post<ArtifactVersion>(`/api/artifacts/${seg(artifactId)}/restore/${seg(versionId)}`);
}

export function approveArtifactVersion(versionId: string) {
    return post<ArtifactVersion>(`/api/artifact-versions/${seg(versionId)}/approve`);
}

export function lockArtifactVersion(versionId: string) {
    return post<ArtifactVersion>(`/api/artifact-versions/${seg(versionId)}/lock`);
}

/** 结构提案落地后的单条结果。 */
export type AppliedStructureChange = {
    action: "move" | "rename" | "reorder" | "delete";
    unit_id: string;
    title: string;
};

export type AcceptProposalResult = {
    proposal: Proposal;
    /** 结构提案不产生 artifact，这两项为 null。 */
    artifact_id: string | null;
    version: ArtifactVersion | null;
    applied?: AppliedStructureChange[];
};

export type ProposalFieldDiff = {
    path: string;
    op: "add" | "remove" | "replace";
    before: unknown;
    after: unknown;
};

/** 结构提案预览里的单条变更描述。 */
export type StructureChangePreview = {
    index: number;
    action: string;
    unit_id: string;
    summary: string;
    title: string;
    applicable: boolean;
    reason?: string;
};

export type ProposalPreview = {
    before: Record<string, unknown>;
    after: Record<string, unknown>;
    field_diffs: ProposalFieldDiff[];
    /** 仅结构提案返回。 */
    changes?: StructureChangePreview[];
};

/** 提案应用后的预览：before / after / 字段级差异。 */
export function previewProposal(proposalId: string) {
    return get<ProposalPreview>(`/api/proposals/${seg(proposalId)}/preview`);
}

/** 采纳提案（可只采纳指定 operation 下标），生成一个新的 artifact 版本。 */
export function acceptProposal(proposalId: string, opIndices?: number[]) {
    return post<AcceptProposalResult>(`/api/proposals/${seg(proposalId)}/accept`, {
        op_indices: opIndices ?? null,
    });
}

export function rejectProposal(proposalId: string) {
    return post<Proposal>(`/api/proposals/${seg(proposalId)}/reject`);
}
