"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    cancelTurn,
    createConversation,
    deleteConversation,
    getConversation,
    listConversations,
    revertTurn,
    startTurn,
    type Conversation,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useConversations(projectId: string, unitId?: string | null) {
    return useQuery({
        queryKey: qk.conversations(projectId, unitId),
        queryFn: () => listConversations(projectId, unitId || undefined),
        enabled: Boolean(projectId),
    });
}

export function useConversation(conversationId: string | null) {
    return useQuery({
        queryKey: qk.conversation(conversationId || ""),
        queryFn: () => getConversation(conversationId as string),
        enabled: Boolean(conversationId),
    });
}

export function useCreateConversation(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (input: { title?: string; unit_id?: string | null }) => createConversation(projectId, input),
        onSuccess: (conversation) => {
            client.setQueryData<Conversation>(qk.conversation(conversation.id), { ...conversation, messages: [] });
            client.invalidateQueries({ queryKey: qk.conversationsRoot(projectId) });
        },
    });
}

export function useDeleteConversation(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (conversationId: string) => deleteConversation(conversationId),
        onSuccess: (_result, conversationId) => {
            client.removeQueries({ queryKey: qk.conversation(conversationId) });
            client.invalidateQueries({ queryKey: qk.conversationsRoot(projectId) });
        },
    });
}

/**
 * 启动 Agent 回合：后端立即返回 turn_id，AI 在后台执行，事件走 SSE。
 * 成功后会刷新对话列表（新消息已落库）。
 */
export function useStartTurn(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({
            conversationId,
            content,
            contextRefs,
            mode,
        }: {
            conversationId: string;
            content: string;
            contextRefs?: Array<Record<string, unknown>>;
            mode?: string;
        }) => startTurn(conversationId, { content, context_refs: contextRefs, mode }),
        onSuccess: (_result, variables) => {
            client.invalidateQueries({ queryKey: qk.conversationsRoot(projectId) });
            client.invalidateQueries({ queryKey: qk.conversation(variables.conversationId) });
        },
    });
}

/** 请求停止正在运行的回合。 */
export function useCancelTurn() {
    return useMutation({
        mutationFn: (turnId: string) => cancelTurn(turnId),
    });
}

/** 撤销本回合直接创建的实体。 */
export function useRevertTurn(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (turnId: string) => revertTurn(turnId),
        onSuccess: () => {
            client.invalidateQueries({ queryKey: qk.project(projectId) });
            client.invalidateQueries({ queryKey: qk.unitsRoot(projectId) });
            client.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
            client.invalidateQueries({ queryKey: qk.assetsRoot(projectId) });
        },
    });
}
