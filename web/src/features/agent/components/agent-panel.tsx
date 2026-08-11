"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PanelRightClose, Plus, Sparkles, Trash2 } from "lucide-react";

import { Composer, type ComposerMode } from "@/features/agent/components/composer";
import { ContextBar, type ContextRef } from "@/features/agent/components/context-bar";
import { MessageList } from "@/features/agent/components/message-list";
import { ProposalCard } from "@/features/agent/components/proposal-card";
import { RunTrace } from "@/features/agent/components/run-trace";
import { TurnActions } from "@/features/agent/components/turn-actions";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { SCRATCH_DRAFT_KEY, useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import type { Proposal } from "@/services/api";
import {
    useCancelTurn,
    useConversation,
    useConversations,
    useCreateConversation,
    useDeleteConversation,
    useHasLlm,
    useRevertTurn,
    useStartTurn,
} from "@/services/queries";
import { qk } from "@/services/queries/keys";
import { useTurnStream } from "@/services/stream/use-turn-stream";
import { cn } from "@/shared/lib/utils";
import { Button, Popconfirm, Text, Tooltip, useApp } from "@/shared/ui";

/**
 * AI 创作助手面板（P1 重写）。
 * <p>
 * 数据流：startTurn 立即返回 turn_id → useTurnStream 订阅 SSE，
 * 运行轨迹 / 流式文本 / 提案卡 / 撤销按钮都由回合事件驱动。
 */
export function AgentPanel({ onCollapse }: { onCollapse?: () => void }) {
    const { message } = useApp();
    const queryClient = useQueryClient();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { selectedUnit, contentArtifacts, unitTree } = useWorkspaceData();
    const hasLlm = useHasLlm();

    const [activeId, setActiveId] = useState<string | null>(null);
    const [turnId, setTurnId] = useState<string | null>(null);
    const [contextRefs, setContextRefs] = useState<ContextRef[]>([]);
    const [mode, setMode] = useState<ComposerMode>("default");

    const conversationsQuery = useConversations(projectId, selectedUnitId);
    const conversationQuery = useConversation(activeId);
    const createConversation = useCreateConversation(projectId);
    const deleteConversation = useDeleteConversation(projectId);
    const startTurn = useStartTurn(projectId);
    const cancelTurn = useCancelTurn();
    const revertTurn = useRevertTurn(projectId);

    const conversations = useMemo(() => conversationsQuery.data || [], [conversationsQuery.data]);
    const draftKey = activeId || SCRATCH_DRAFT_KEY;
    const draft = useWorkspaceStore((state) => state.composerDrafts[draftKey] || "");
    const setComposerDraft = useWorkspaceStore((state) => state.setComposerDraft);
    const clearComposerDraft = useWorkspaceStore((state) => state.clearComposerDraft);
    const drainContextRefs = useWorkspaceStore((state) => state.drainContextRefs);
    // 监听待注入数量：结构面板“交给 Agent”后立即取走，而不是等下次切单元。
    const pendingRefsCount = useWorkspaceStore((state) => state.pendingContextRefs.length);

    const stream = useTurnStream(activeId, turnId);
    const running = stream.status === "running";

    // 回合结束后把持久化的助手消息拉进消息流。
    // 流式文本只在 running 期间渲染，这里不刷新的话，上一轮回复会在开下一轮时凭空消失。
    // 同时刷新项目数据：按决策 C，Agent 的追加操作（建稿件/建单元/生成素材）不走提案，
    // 没有别的时机会触发画布更新。
    useEffect(() => {
        if (!activeId || !turnId) return;
        if (stream.status === "idle" || stream.status === "running") return;
        queryClient.invalidateQueries({ queryKey: qk.conversation(activeId) });
        queryClient.invalidateQueries({ queryKey: qk.project(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.unitsRoot(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.assetsRoot(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.jobs(projectId) });
    }, [activeId, projectId, queryClient, stream.status, turnId]);

    // T5.3：屏幕阅读器播报当前工具动作；流式正文本身在 MessageList 里已带 aria-live。
    const liveStatus = useMemo(() => {
        if (!running) return "";
        const activeStep = [...stream.steps].reverse().find((step) => step.status === "running");
        return activeStep ? `AI 助手正在执行工具：${activeStep.tool_name}` : "AI 助手正在处理你的请求";
    }, [running, stream.steps]);

    const flatUnits = useMemo(() => {
        const result: typeof unitTree = [];
        const walk = (nodes: typeof unitTree) => {
            nodes.forEach((node) => {
                result.push(node);
                walk(node.children);
            });
        };
        walk(unitTree);
        return result;
    }, [unitTree]);

    // 切换单元后当前对话可能已不在作用域内，回落到该作用域的第一个对话。
    useEffect(() => {
        if (activeId && conversations.some((item) => item.id === activeId)) return;
        setActiveId(conversations[0]?.id ?? null);
        setTurnId(null);
        setContextRefs([]);
    }, [activeId, conversations]);

    // 结构面板多选后“交给 Agent”：挂载/切单元时取走待注入的上下文引用。
    useEffect(() => {
        const refs = drainContextRefs();
        if (!refs.length) return;
        setContextRefs((current) => {
            const existing = new Set(current.map((ref) => `${ref.type}:${ref.id || ref.section || ""}`));
            const fresh = refs
                .filter((ref) => !existing.has(`${ref.type}:${ref.id || ""}`))
                .map((ref) => ({ type: ref.type as ContextRef["type"], id: ref.id, label: ref.label }));
            return fresh.length ? [...current, ...fresh] : current;
        });
    }, [projectId, selectedUnitId, drainContextRefs, pendingRefsCount]);

    const messages = conversationQuery.data?.messages || [];
    const scopeLabel = selectedUnit ? selectedUnit.title : "整个项目";

    const refreshProjectData = () => {
        queryClient.invalidateQueries({ queryKey: qk.project(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
        queryClient.invalidateQueries({ queryKey: qk.unitsRoot(projectId) });
    };

    const submit = async () => {
        const content = draft.trim();
        if (!content || running) return;
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
            setTurnId(null);
            const result = await startTurn.mutateAsync({
                conversationId,
                content,
                contextRefs: contextRefs.map((ref) => ({
                    type: ref.type,
                    id: ref.id,
                    section: ref.section,
                })),
                mode,
            });
            setTurnId(result.turn_id);
            setContextRefs([]);
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
            setTurnId(null);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "对话创建失败");
        }
    };

    const removeConversation = async (conversationId: string) => {
        try {
            await deleteConversation.mutateAsync(conversationId);
            setActiveId(null);
            setTurnId(null);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col bg-[var(--s-panel)]">
            <div role="status" aria-live="polite" className="sr-only">
                {liveStatus}
            </div>
            <div className="flex items-center justify-between gap-2 border-b border-[var(--hairline)] px-3 py-3">
                <div className="flex min-w-0 items-center gap-2.5">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-action-soft)] text-[var(--s-action)]">
                        <Sparkles className="size-4" />
                    </span>
                    <div className="min-w-0">
                        <Text as="div" variant="body" tone="ink" weight={600}>
                            AI 创作助手
                        </Text>
                        <Text variant="caption" tone="faint" truncate className="mt-0.5 block">
                            作用于：{scopeLabel} · {hasLlm ? "已连接" : "需要配置模型"}
                        </Text>
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Tooltip title="新对话">
                        <Button
                            size="sm"
                            variant="ghost"
                            aria-label="新对话"
                            icon={<Plus className="size-4" />}
                            loading={createConversation.isPending}
                            onClick={() => void startNewConversation()}
                        />
                    </Tooltip>
                    {onCollapse ? (
                        <Tooltip title="收起助手（⌘J）">
                            <Button
                                size="sm"
                                variant="ghost"
                                aria-label="收起助手"
                                icon={<PanelRightClose className="size-4" />}
                                onClick={onCollapse}
                            />
                        </Tooltip>
                    ) : null}
                </div>
            </div>

            {conversations.length ? (
                <div className="hide-scrollbar flex items-center gap-1.5 overflow-x-auto border-b border-[var(--hairline)] px-3 py-2">
                    {conversations.map((item) => (
                        <button
                            key={item.id}
                            type="button"
                            onClick={() => {
                                setActiveId(item.id);
                                setTurnId(null);
                            }}
                            className={cn(
                                "shrink-0 rounded-full px-2.5 py-1 text-caption transition-colors",
                                activeId === item.id
                                    ? "bg-[var(--s-raised)] text-[var(--s-ink)]"
                                    : "bg-[var(--s-raised)] text-[var(--s-muted)] hover:text-[var(--s-ink)]",
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
                                className="shrink-0 px-1 text-[var(--s-faint)] transition-colors hover:text-[var(--s-danger)]"
                                aria-label="删除当前对话"
                            >
                                <Trash2 className="size-3.5" />
                            </button>
                        </Popconfirm>
                    ) : null}
                </div>
            ) : null}

            <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto p-3">
                <ContextBar
                    refs={contextRefs}
                    onChange={setContextRefs}
                    units={flatUnits}
                    artifacts={contentArtifacts}
                />
                <RunTrace steps={stream.steps} running={running} />
                <MessageList
                    messages={messages}
                    pending={running}
                    streamingText={stream.text}
                    onPickPrompt={(prompt) => setComposerDraft(draftKey, prompt)}
                />
                {stream.proposals.map((proposal) => (
                    <ProposalCard
                        key={String(proposal.id)}
                        proposal={proposal as Proposal}
                        onChanged={refreshProjectData}
                    />
                ))}
            </div>

            <TurnActions
                turnId={turnId}
                entities={stream.entities}
                onReverted={() => {
                    setTurnId(null);
                    queryClient.invalidateQueries({ queryKey: qk.conversation(activeId || "") });
                }}
                onChanged={refreshProjectData}
            />

            <Composer
                value={draft}
                onChange={(value) => setComposerDraft(draftKey, value)}
                onSubmit={() => void submit()}
                onStop={() => {
                    if (turnId) void cancelTurn.mutateAsync(turnId);
                }}
                pending={running}
                hasLlm={hasLlm}
                scopeLabel={scopeLabel}
                mode={mode}
                onModeChange={setMode}
            />
        </div>
    );
}
