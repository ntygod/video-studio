"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Popconfirm, Tooltip } from "antd";
import { PanelRightClose, Plus, Trash2 } from "lucide-react";

import { Composer } from "@/features/agent/components/composer";
import { MessageList } from "@/features/agent/components/message-list";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore, SCRATCH_DRAFT_KEY } from "@/features/workspace/stores/use-workspace-store";
import {
    useConversation,
    useConversations,
    useCreateConversation,
    useDeleteConversation,
    useHasLlm,
    useSendMessage,
} from "@/services/queries";
import { cn } from "@/shared/lib/utils";

/**
 * AI 创作助手面板。
 * <p>
 * P0 保持既有能力（多对话、Markdown 渲染、按单元作用域），只把数据流换成 React Query
 * 并去掉全量刷新。流式输出、运行轨迹、上下文条与内联提案卡片在 P1 加入。
 */
export function AgentPanel({ onCollapse }: { onCollapse?: () => void }) {
    const { message } = App.useApp();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { selectedUnit } = useWorkspaceData();
    const hasLlm = useHasLlm();

    const [activeId, setActiveId] = useState<string | null>(null);

    const conversationsQuery = useConversations(projectId, selectedUnitId);
    const conversationQuery = useConversation(activeId);
    const createConversation = useCreateConversation(projectId);
    const deleteConversation = useDeleteConversation(projectId);
    const sendMessage = useSendMessage(projectId);

    const conversations = useMemo(() => conversationsQuery.data || [], [conversationsQuery.data]);

    const draftKey = activeId || SCRATCH_DRAFT_KEY;
    const draft = useWorkspaceStore((state) => state.composerDrafts[draftKey] || "");
    const setComposerDraft = useWorkspaceStore((state) => state.setComposerDraft);
    const clearComposerDraft = useWorkspaceStore((state) => state.clearComposerDraft);

    // 切换单元后当前对话可能已不在作用域内，回落到该作用域的第一个对话。
    useEffect(() => {
        if (activeId && conversations.some((item) => item.id === activeId)) return;
        setActiveId(conversations[0]?.id ?? null);
    }, [activeId, conversations]);

    const messages = conversationQuery.data?.messages || [];
    const scopeLabel = selectedUnit ? selectedUnit.title : "整个项目";

    const submit = async () => {
        const content = draft.trim();
        if (!content || sendMessage.isPending) return;
        if (!hasLlm) {
            message.warning("请先在模型设置中启用一个 AI 模型");
            return;
        }

        try {
            let conversationId = activeId;
            if (!conversationId) {
                const created = await createConversation.mutateAsync({
                    title: content.slice(0, 24),
                    unit_id: selectedUnitId,
                });
                conversationId = created.id;
                setActiveId(created.id);
            }

            clearComposerDraft(draftKey);
            const result = await sendMessage.mutateAsync({ conversationId, content });
            if (result.proposals.length) {
                message.info(`AI 提出了 ${result.proposals.length} 项可审核修改`);
            }
        } catch (error) {
            // 失败时把内容还给输入框，避免用户重打一遍。
            setComposerDraft(draftKey, content);
            message.error(error instanceof Error ? error.message : "发送失败");
        }
    };

    const startNewConversation = async () => {
        try {
            const created = await createConversation.mutateAsync({ title: "创作讨论", unit_id: selectedUnitId });
            setActiveId(created.id);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "对话创建失败");
        }
    };

    const removeConversation = async (conversationId: string) => {
        try {
            await deleteConversation.mutateAsync(conversationId);
            setActiveId(null);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col bg-[var(--studio-surface)]">
            <div className="flex items-center justify-between gap-2 border-b border-[var(--studio-line)] px-3 py-2.5">
                <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-[var(--studio-ink)]">AI 创作助手</div>
                    <div className="mt-0.5 truncate text-[10px] text-[var(--studio-faint)]">
                        {scopeLabel} · {hasLlm ? "可以开始对话" : "需要先配置模型"}
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Tooltip title="新对话">
                        <Button
                            size="small"
                            type="text"
                            aria-label="新对话"
                            icon={<Plus className="size-4" />}
                            loading={createConversation.isPending}
                            onClick={() => void startNewConversation()}
                        />
                    </Tooltip>
                    {onCollapse ? (
                        <Tooltip title="收起助手（⌘J）">
                            <Button
                                size="small"
                                type="text"
                                aria-label="收起助手"
                                icon={<PanelRightClose className="size-4" />}
                                onClick={onCollapse}
                            />
                        </Tooltip>
                    ) : null}
                </div>
            </div>

            {conversations.length ? (
                <div className="hide-scrollbar flex items-center gap-1.5 overflow-x-auto border-b border-[var(--studio-line)] px-3 py-2">
                    {conversations.map((item) => (
                        <button
                            key={item.id}
                            type="button"
                            onClick={() => setActiveId(item.id)}
                            className={cn(
                                "shrink-0 rounded-full px-2.5 py-1 text-[11px] transition-colors",
                                activeId === item.id
                                    ? "bg-[var(--studio-action)] text-[var(--studio-action-foreground)]"
                                    : "bg-[var(--studio-surface-raised)] text-[var(--studio-muted)] hover:text-[var(--studio-ink)]",
                            )}
                        >
                            {item.title}
                        </button>
                    ))}
                    {activeId ? (
                        <Popconfirm
                            title="删除此对话？"
                            okText="删除"
                            cancelText="取消"
                            onConfirm={() => void removeConversation(activeId)}
                        >
                            <button
                                type="button"
                                className="shrink-0 px-1 text-[var(--studio-faint)] transition-colors hover:text-[var(--studio-danger)]"
                                aria-label="删除当前对话"
                            >
                                <Trash2 className="size-3.5" />
                            </button>
                        </Popconfirm>
                    ) : null}
                </div>
            ) : null}

            <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto p-3">
                <MessageList
                    messages={messages}
                    pending={sendMessage.isPending}
                    onPickPrompt={(prompt) => setComposerDraft(draftKey, prompt)}
                />
            </div>

            <Composer
                value={draft}
                onChange={(value) => setComposerDraft(draftKey, value)}
                onSubmit={() => void submit()}
                pending={sendMessage.isPending}
                hasLlm={hasLlm}
                scopeLabel={scopeLabel}
            />
        </div>
    );
}
