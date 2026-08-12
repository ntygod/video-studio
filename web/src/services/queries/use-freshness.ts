"use client";

import {
    useMutation,
    useQuery,
    useQueryClient,
} from "@tanstack/react-query";

import {
    getArtifactImpact,
    getProjectArtifactFreshness,
    previewRegenerationCascade,
    regenerateArtifact,
    type RegenerationPreviewInput,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useProjectArtifactFreshness(
    projectId: string,
    includeFresh = false,
) {
    return useQuery({
        queryKey: qk.freshness(projectId, includeFresh),
        queryFn: () =>
            getProjectArtifactFreshness(projectId, includeFresh),
        enabled: Boolean(projectId),
        staleTime: 5_000,
        refetchInterval: 15_000,
        refetchOnWindowFocus: true,
    });
}

export function useArtifactImpact(
    artifactId: string | null,
    enabled = true,
) {
    return useQuery({
        queryKey: qk.artifactImpact(artifactId || ""),
        queryFn: () => getArtifactImpact(artifactId as string),
        enabled: Boolean(artifactId && enabled),
        staleTime: 10_000,
    });
}

export function usePreviewRegenerationCascade(
    projectId: string,
) {
    return useMutation({
        mutationFn: (input: RegenerationPreviewInput) =>
            previewRegenerationCascade(projectId, input),
    });
}

export function useRegenerateArtifact(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (artifactId: string) =>
            regenerateArtifact(artifactId),
        onSuccess: () => {
            client.invalidateQueries({
                queryKey: qk.jobsRoot(),
            });
            client.invalidateQueries({
                queryKey: qk.artifactsRoot(projectId),
            });
            client.invalidateQueries({
                queryKey: qk.freshnessRoot(projectId),
            });
        },
    });
}
