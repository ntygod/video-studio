"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    acceptProposal,
    addArtifactVersion,
    approveArtifactVersion,
    diffArtifactVersions,
    listArtifactVersions,
    listArtifacts,
    listProposals,
    lockArtifactVersion,
    rejectProposal,
    restoreArtifactVersion,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useArtifacts(projectId: string, unitId?: string | null, includePayload = false) {
    return useQuery({
        queryKey: [...qk.artifacts(projectId, unitId), includePayload],
        queryFn: () => listArtifacts(projectId, unitId || undefined, includePayload),
        enabled: Boolean(projectId),
    });
}

/** 待处理提案（分页行走）。 */
export function useProposals(projectId: string) {
    return useQuery({
        queryKey: qk.proposalsRoot(projectId),
        queryFn: () => listProposals(projectId, "pending"),
        enabled: Boolean(projectId),
    });
}

/**
 * 稿件变更后需要作废的作用域：稿件列表 + 待处理提案 + 项目统计 + Freshness。
 */
function useInvalidateArtifacts(projectId: string) {
    const client = useQueryClient();
    return () => {
        client.invalidateQueries({ queryKey: qk.project(projectId) });
        client.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
        client.invalidateQueries({ queryKey: qk.proposalsRoot(projectId) });
        client.invalidateQueries({ queryKey: qk.freshnessRoot(projectId) });
    };
}

export function useAddArtifactVersion(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: ({ artifactId, payload, note }: { artifactId: string; payload: Record<string, unknown>; note?: string }) =>
            addArtifactVersion(artifactId, payload, note ?? ""),
        onSuccess: invalidate,
    });
}

export function useApproveArtifactVersion(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: (versionId: string) => approveArtifactVersion(versionId),
        onSuccess: invalidate,
    });
}

/** 某份稿件的全部版本（按版本号倒序）。 */
export function useArtifactVersions(artifactId: string | null) {
    return useQuery({
        queryKey: ["artifact-versions", artifactId || ""],
        queryFn: () => listArtifactVersions(artifactId as string),
        enabled: Boolean(artifactId),
    });
}

/** 两个版本的结构化 diff。 */
export function useVersionDiff(versionA: string | null, versionB: string | null) {
    return useQuery({
        queryKey: ["artifact-diff", versionA || "", versionB || ""],
        queryFn: () => diffArtifactVersions(versionA as string, versionB as string),
        enabled: Boolean(versionA && versionB && versionA !== versionB),
    });
}

/** 回滚到目标版本（追加新版本）。 */
export function useRestoreArtifactVersion(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: ({ artifactId, versionId }: { artifactId: string; versionId: string }) =>
            restoreArtifactVersion(artifactId, versionId),
        onSuccess: invalidate,
    });
}

export function useLockArtifactVersion(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: (versionId: string) => lockArtifactVersion(versionId),
        onSuccess: invalidate,
    });
}

export function useAcceptProposal(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: (proposalId: string) => acceptProposal(proposalId),
        onSuccess: invalidate,
    });
}

export function useRejectProposal(projectId: string) {
    const invalidate = useInvalidateArtifacts(projectId);
    return useMutation({
        mutationFn: (proposalId: string) => rejectProposal(proposalId),
        onSuccess: invalidate,
    });
}
