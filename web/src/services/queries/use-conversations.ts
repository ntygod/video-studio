"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    createConversation,
    deleteConversation,
    getConversation,
    listConversations,
    sendMessage,
    type Conversation,
    type ConversationMessage,
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

/** 本地占位消息的 id 前缀，用于在回包后剔除乐观条目。 */
const OPTIMISTIC_PREFIX = "optimistic-";

/** 判断一条消息是否为尚未落库的乐观占位。 */
export function isOptimisticMessage(message: ConversationMessage): boolean {
    return message.id.startsWith(OPTIMISTIC_PREFIX);
}

/**
 * 发送消息。
 * <p>
 * 先乐观追加用户消息让输入框立即清空，回包后用服务端的真实消息替换。
 * AI 若提出提案，需要同时作废项目详情与稿件缓存。
 *
 * 注意：后端当前是阻塞式的，一次调用可能等待很久。P1 换成 SSE 后本 hook 只保留为降级路径。
 */
export function useSendMessage(projectId: string) {
    const client = useQueryClient();

    return useMutation({
        mutationFn: ({ conversationId, content }: { conversationId: string; content: string }) =>
            sendMessage(conversationId, content),

        onMutate: async ({ conversationId, content }) => {
            const key = qk.conversation(conversationId);
            await client.cancelQueries({ queryKey: key });
            const previous = client.getQueryData<Conversation>(key);

            const optimistic: ConversationMessage = {
                id: OPTIMISTIC_PREFIX + String(previous?.messages?.length ?? 0),
                conversation_id: conversationId,
                seq: (previous?.messages?.length || 0) + 1,
                role: "user",
                content,
                proposal_ids: [],
                created_at: Date.now() / 1000,
            };

            client.setQueryData<Conversation>(key, (current) =>
                current ? { ...current, messages: [...(current.messages || []), optimistic] } : current,
            );

            return { previous, key };
        },

        onError: (_error, _variables, context) => {
            if (context?.previous) client.setQueryData(context.key, context.previous);
        },

        onSuccess: (result, { conversationId }) => {
            client.setQueryData<Conversation>(qk.conversation(conversationId), (current) => {
                if (!current) return current;
                const settled = (current.messages || []).filter((item) => !isOptimisticMessage(item));
                return { ...current, messages: [...settled, result.user_message, result.assistant_message] };
            });
            client.invalidateQueries({ queryKey: qk.conversationsRoot(projectId) });
            if (result.proposals.length) {
                client.invalidateQueries({ queryKey: qk.project(projectId) });
                client.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
            }
        },
    });
}
