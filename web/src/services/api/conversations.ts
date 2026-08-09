"use client";

import { del, get, post, seg } from "./http";
import type { Conversation, OkResult, SendMessageResult } from "./types";

export function listConversations(projectId: string, unitId?: string) {
    return get<Conversation[]>(`/api/projects/${seg(projectId)}/conversations`, { unit_id: unitId });
}

export function createConversation(projectId: string, input: { title?: string; unit_id?: string | null }) {
    return post<Conversation>(`/api/projects/${seg(projectId)}/conversations`, input);
}

export function getConversation(id: string) {
    return get<Conversation>(`/api/conversations/${seg(id)}`);
}

export function deleteConversation(id: string) {
    return del<OkResult>(`/api/conversations/${seg(id)}`);
}

/**
 * 发送一条消息并等待 AI 回复。
 * <p>
 * 当前后端为阻塞式：整个 LLM 调用完成后才返回，最坏情况下会等待很久。
 * P1 会替换为 SSE 流式接口，届时本函数保留为降级路径。
 */
export function sendMessage(conversationId: string, content: string) {
    return post<SendMessageResult>(`/api/conversations/${seg(conversationId)}/messages`, { content });
}
