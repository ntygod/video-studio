"use client";

import { del, get, post, seg } from "./http";
import type { AgentTurn, Conversation, OkResult, StartTurnResult } from "./types";

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

/** 启动一个 Agent 回合：立即返回 turn_id，AI 在后台线程执行，事件走 SSE。 */
export function startTurn(
    conversationId: string,
    input: { content: string; context_refs?: Array<Record<string, unknown>>; mode?: string },
) {
    return post<StartTurnResult>(`/api/conversations/${seg(conversationId)}/turns`, input);
}

/** 读取回合与步骤（SSE 重连后的种子数据/降级轮询）。 */
export function getTurn(turnId: string) {
    return get<AgentTurn>(`/api/turns/${seg(turnId)}`);
}

/** 请求取消正在运行的回合。 */
export function cancelTurn(turnId: string) {
    return post<OkResult>(`/api/turns/${seg(turnId)}/cancel`);
}

/** 撤销本回合直接创建的实体。 */
export function revertTurn(turnId: string) {
    return post<{ turn: AgentTurn; reverted: Array<{ type: string; id: string }>; skipped: Array<{ type: string; id: string }> }>(
        `/api/turns/${seg(turnId)}/revert`,
    );
}
