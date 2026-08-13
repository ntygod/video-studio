"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    approveRuntimePolicyDecision,
    denyRuntimePolicyDecision,
    getActiveConversationTurn,
    getProjectRuntimeCostPolicy,
    getTurnRuntimeBudget,
    listProjectPolicyDecisions,
    listTurnPolicyDecisions,
    listTurnRuntimeCosts,
    patchProjectRuntimeCostPolicy,
    type RuntimePolicyDecision,
    type RuntimePolicyDecisionStatus,
    type UnpricedProviderMode,
} from "@/services/api";
import { qk } from "./keys";

export function useActiveConversationTurn(
    projectId: string,
    conversationId: string | null,
) {
    return useQuery({
        queryKey: qk.activeConversationTurn(
            projectId,
            conversationId || "",
        ),
        queryFn: () =>
            getActiveConversationTurn(
                projectId,
                conversationId as string,
            ),
        enabled: Boolean(projectId && conversationId),
        staleTime: 1_000,
        refetchInterval: (query) =>
            query.state.data ? 2_000 : false,
        refetchOnWindowFocus: true,
    });
}

export function useTurnPolicyDecisions(
    turnId: string | null,
    active = true,
) {
    return useQuery({
        queryKey: qk.turnPolicyDecisions(turnId || ""),
        queryFn: () => listTurnPolicyDecisions(turnId as string),
        enabled: Boolean(turnId),
        staleTime: 1_000,
        refetchInterval: (query) =>
            active ||
            query.state.data?.some(
                (decision) => decision.status === "pending",
            )
                ? 1_500
                : false,
        refetchOnWindowFocus: true,
    });
}

export function useProjectPolicyDecisions(
    projectId: string,
    status: RuntimePolicyDecisionStatus = "pending",
) {
    return useQuery({
        queryKey: qk.projectPolicyDecisions(projectId, status),
        queryFn: () => listProjectPolicyDecisions(projectId, status),
        enabled: Boolean(projectId),
        staleTime: 2_000,
        refetchInterval: 5_000,
        refetchOnWindowFocus: true,
    });
}

export function useProjectRuntimeCostPolicy(projectId: string) {
    return useQuery({
        queryKey: qk.projectRuntimeCostPolicy(projectId),
        queryFn: () => getProjectRuntimeCostPolicy(projectId),
        enabled: Boolean(projectId),
        staleTime: 10_000,
        refetchOnWindowFocus: true,
    });
}

export function useUpdateProjectRuntimeCostPolicy(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({
            expectedRevision,
            mode,
        }: {
            expectedRevision: number;
            mode: UnpricedProviderMode;
        }) =>
            patchProjectRuntimeCostPolicy(projectId, {
                expected_revision: expectedRevision,
                unpriced_provider_mode: mode,
            }),
        onSuccess: (state) => {
            client.setQueryData(
                qk.projectRuntimeCostPolicy(projectId),
                state,
            );
            client.invalidateQueries({ queryKey: qk.project(projectId) });
            client.invalidateQueries({ queryKey: qk.projects() });
        },
    });
}

export function useTurnRuntimeBudget(
    turnId: string | null,
    active = false,
) {
    return useQuery({
        queryKey: qk.turnRuntimeBudget(turnId || ""),
        queryFn: () => getTurnRuntimeBudget(turnId as string),
        enabled: Boolean(turnId),
        staleTime: 1_000,
        refetchInterval: (query) =>
            active ||
            ["queued", "running"].includes(
                query.state.data?.plan_status || "",
            )
                ? 2_000
                : false,
        refetchOnWindowFocus: true,
    });
}

export function useTurnRuntimeCosts(
    turnId: string | null,
    active = false,
) {
    return useQuery({
        queryKey: qk.turnRuntimeCosts(turnId || ""),
        queryFn: () => listTurnRuntimeCosts(turnId as string),
        enabled: Boolean(turnId),
        staleTime: 1_000,
        refetchInterval: active ? 2_000 : false,
        refetchOnWindowFocus: true,
    });
}

export function useResolveRuntimePolicyDecision(
    turnId: string | null,
    projectId?: string | null,
) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({
            decisionId,
            approved,
            note = "",
        }: {
            decisionId: string;
            approved: boolean;
            note?: string;
        }) =>
            approved
                ? approveRuntimePolicyDecision(decisionId, note)
                : denyRuntimePolicyDecision(decisionId, note),
        onSuccess: (decision) => {
            const targetTurnId =
                turnId || String(decision.context.turn_id || "");
            if (targetTurnId) {
                client.setQueryData<RuntimePolicyDecision[]>(
                    qk.turnPolicyDecisions(targetTurnId),
                    (current = []) =>
                        current.map((item) =>
                            item.id === decision.id ? decision : item,
                        ),
                );
                client.invalidateQueries({
                    queryKey: qk.turnRuntimeBudget(targetTurnId),
                });
                client.invalidateQueries({
                    queryKey: qk.turnRuntimeCosts(targetTurnId),
                });
            }
            if (projectId) {
                client.invalidateQueries({
                    queryKey: qk.projectPolicyDecisions(
                        projectId,
                        "pending",
                    ),
                });
            }
        },
    });
}
