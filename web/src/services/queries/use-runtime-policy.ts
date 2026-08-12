"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    approveRuntimePolicyDecision,
    denyRuntimePolicyDecision,
    getActiveConversationTurn,
    listTurnPolicyDecisions,
    type RuntimePolicyDecision,
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
            active || query.state.data?.some(
                (decision) => decision.status === "pending",
            )
                ? 1_500
                : false,
        refetchOnWindowFocus: true,
    });
}

export function useResolveRuntimePolicyDecision(turnId: string | null) {
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
            if (!turnId) return;
            client.setQueryData<RuntimePolicyDecision[]>(
                qk.turnPolicyDecisions(turnId),
                (current = []) =>
                    current.map((item) =>
                        item.id === decision.id ? decision : item,
                    ),
            );
        },
    });
}
