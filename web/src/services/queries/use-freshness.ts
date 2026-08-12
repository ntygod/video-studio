"use client";

import {
    useMutation,
    useQuery,
    useQueryClient,
} from "@tanstack/react-query";

import {
    cancelRegenerationPlan,
    createRegenerationPlan,
    getArtifactAssetDependencies,
    getArtifactImpact,
    getProjectArtifactFreshness,
    getRegenerationPlan,
    listRegenerationPlans,
    previewRegenerationCascade,
    regenerateArtifact,
    setRegenerationPlanStepInput,
    startRegenerationPlan,
    type RegenerationPlan,
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

export function useArtifactAssetDependencies(
    artifactId: string | null,
    enabled = true,
) {
    return useQuery({
        queryKey: qk.artifactAssetDependencies(artifactId || ""),
        queryFn: () =>
            getArtifactAssetDependencies(artifactId as string),
        enabled: Boolean(artifactId && enabled),
        staleTime: 5_000,
    });
}

export function usePreviewRegenerationCascade(projectId: string) {
    return useMutation({
        mutationFn: (input: RegenerationPreviewInput) =>
            previewRegenerationCascade(projectId, input),
    });
}

export function useRegenerationPlans(projectId: string) {
    return useQuery({
        queryKey: qk.regenerationPlansRoot(projectId),
        queryFn: () => listRegenerationPlans(projectId),
        enabled: Boolean(projectId),
        staleTime: 10_000,
    });
}

export function useRegenerationPlan(planId: string | null) {
    return useQuery({
        queryKey: qk.regenerationPlan(planId || ""),
        queryFn: () => getRegenerationPlan(planId as string),
        enabled: Boolean(planId),
        refetchInterval: (query) =>
            query.state.data?.status === "running" ? 2_000 : false,
        refetchOnWindowFocus: true,
    });
}

function useUpdatePlanCaches(projectId: string) {
    const client = useQueryClient();
    return (plan: RegenerationPlan) => {
        client.setQueryData(qk.regenerationPlan(plan.id), plan);
        client.invalidateQueries({
            queryKey: qk.regenerationPlansRoot(projectId),
        });
        client.invalidateQueries({
            queryKey: qk.freshnessRoot(projectId),
        });
        client.invalidateQueries({
            queryKey: qk.artifactsRoot(projectId),
        });
        client.invalidateQueries({ queryKey: qk.jobsRoot() });
    };
}

export function useCreateRegenerationPlan(projectId: string) {
    const update = useUpdatePlanCaches(projectId);
    return useMutation({
        mutationFn: (input: RegenerationPreviewInput) =>
            createRegenerationPlan(projectId, input),
        onSuccess: update,
    });
}

export function useStartRegenerationPlan(projectId: string) {
    const update = useUpdatePlanCaches(projectId);
    return useMutation({
        mutationFn: (planId: string) => startRegenerationPlan(planId),
        onSuccess: update,
    });
}

export function useCancelRegenerationPlan(projectId: string) {
    const update = useUpdatePlanCaches(projectId);
    return useMutation({
        mutationFn: (planId: string) => cancelRegenerationPlan(planId),
        onSuccess: update,
    });
}

export function useSetRegenerationPlanStepInput(projectId: string) {
    const update = useUpdatePlanCaches(projectId);
    return useMutation({
        mutationFn: ({
            stepId,
            replacements,
        }: {
            stepId: string;
            replacements: Record<string, string>;
        }) => setRegenerationPlanStepInput(stepId, replacements),
        onSuccess: update,
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
