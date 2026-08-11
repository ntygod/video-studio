"use client";

import { useQuery } from "@tanstack/react-query";

import {
    getArtifactImpact,
    getProjectArtifactFreshness,
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
