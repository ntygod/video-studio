"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    acceptProposal,
    addArtifactVersion,
    approveArtifactVersion,
    listArtifacts,
    lockArtifactVersion,
    rejectProposal,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useArtifacts(projectId: string, unitId?: string | null) {
    return useQuery({
        queryKey: qk.artifacts(projectId, unitId),
        queryFn: () => listArtifacts(projectId, unitId || undefined),
        enabled: Boolean(projectId),
    });
}

/**
 * 稿件变更后需要作废的作用域。
 * <p>
 * 项目详情内嵌了 artifacts 与 pending_proposals，所以两处都要动；
 * artifactsRoot 覆盖该项目下所有单元的稿件列表。
 */
function useInvalidateArtifacts(projectId: string) {
    const client = useQueryClient();
    return () => {
        client.invalidateQueries({ queryKey: qk.project(projectId) });
        client.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
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
