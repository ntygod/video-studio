"use client";

import { useRef } from "react";
import {
    useMutation,
    useQuery,
    useQueryClient,
} from "@tanstack/react-query";

import {
    getRegenerationPlanLineage,
    replanRegenerationPlan,
    type ReplanRegenerationPlanInput,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

function newReplanClientToken(): string {
    if (typeof globalThis.crypto?.randomUUID === "function") {
        return globalThis.crypto.randomUUID();
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function useRegenerationPlanLineage(planId: string | null) {
    return useQuery({
        queryKey: qk.regenerationPlanLineage(planId || ""),
        queryFn: () => getRegenerationPlanLineage(planId as string),
        enabled: Boolean(planId),
        staleTime: 10_000,
        refetchOnWindowFocus: true,
    });
}

export function useReplanRegenerationPlan(projectId: string) {
    const client = useQueryClient();
    const tokenRef = useRef(newReplanClientToken());
    return useMutation({
        mutationFn: ({
            planId,
            input,
        }: {
            planId: string;
            input: ReplanRegenerationPlanInput;
        }) =>
            replanRegenerationPlan(planId, {
                ...input,
                client_token: input.client_token || tokenRef.current,
            }),
        onSuccess: (target, variables) => {
            tokenRef.current = newReplanClientToken();
            client.setQueryData(qk.regenerationPlan(target.id), target);
            client.invalidateQueries({
                queryKey: qk.regenerationPlan(variables.planId),
            });
            client.invalidateQueries({
                queryKey: qk.regenerationPlanLineage(variables.planId),
            });
            client.invalidateQueries({
                queryKey: qk.regenerationPlanLineage(target.id),
            });
            client.invalidateQueries({
                queryKey: qk.regenerationPlansRoot(projectId),
            });
            client.invalidateQueries({
                queryKey: qk.freshnessRoot(projectId),
            });
            client.invalidateQueries({
                queryKey: qk.artifactsRoot(projectId),
            });
        },
    });
}
