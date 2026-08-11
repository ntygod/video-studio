"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, FileText, Lock } from "lucide-react";
import Link from "next/link";

import { ArtifactEditorModal } from "@/features/canvas/components/artifact-editor-modal";
import { StoryRenderer } from "@/features/canvas/story/renderers";
import {
    freshnessByArtifact,
    freshnessMeta,
    freshnessReason,
} from "@/features/workspace/lib/freshness";
import { artifactKindLabel, artifactStatusLabel } from "@/features/workspace/lib/labels";
import { SCRATCH_DRAFT_KEY, useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import type { Artifact } from "@/services/api";
import {
    useApproveArtifactVersion,
    useLockArtifactVersion,
    useProjectArtifactFreshness,
} from "@/services/queries";
import { useIsAgentInline } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";
import {
    Button,
    Chip,
    StatusDot,
    Surface,
    Tag,
    Text,
    Tooltip,
    useApp,
} from "@/shared/ui";

function versionsHref(
    projectId: string,
    artifactId: string,
    unitId?: string | null,
): string {
    const query = new URLSearchParams({ artifact: artifactId });
    if (unitId) query.set("unit", unitId);
    return `/projects/${encodeURIComponent(projectId)}/versions?${query.toString()}`;
}

/**
 * 创作稿件列表与内容。
 * <p>
 * 上半部分是同一作用域下的稿件切换器，下半部分渲染选中稿件的当前版本。
 */
export function ArtifactPanel({ projectId, artifacts }: { projectId: string; artifacts: Artifact[] }) {
    const { message } = useApp();
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [editorOpen, setEditorOpen] = useState(false);

    const approveVersion = useApproveArtifactVersion(projectId);
    const lockVersion = useLockArtifactVersion(projectId);
    const freshnessQuery = useProjectArtifactFreshness(projectId);
    const freshnessMap = useMemo(
        () => freshnessByArtifact(freshnessQuery.data?.items || []),
        [freshnessQuery.data?.items],
    );
    const setComposerDraft = useWorkspaceStore((state) => state.setComposerDraft);
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);
    const agentInline = useIsAgentInline();

    /** 块级改写：把该块预填进助手输入框并打开助手面板。 */
    const rewriteBlock = (text: string) => {
        setComposerDraft(SCRATCH_DRAFT_KEY, `改写这段：\n${text}`);
        if (agentInline) {
            if (agentCollapsed) toggleAgent();
        } else {
            setAgentDrawer(true);
        }
    };

    // 稿件列表变化后（切换单元、采纳提案）保持选中项有效。
    useEffect(() => {
        setSelectedId((current) => {
            if (current && artifacts.some((item) => item.id === current)) return current;
            return artifacts[0]?.id ?? null;
        });
    }, [artifacts]);

    const selected = artifacts.find((item) => item.id === selectedId) || null;
    const version = selected?.current_version;
    const locked = version?.status === "locked";
    const selectedFreshness = selected
        ? freshnessMap.get(selected.id) || null
        : null;
    const invalidInputs =
        selectedFreshness?.status === "stale" ||
        selectedFreshness?.status === "blocked";
    const statusDisabled = locked || invalidInputs;
    const statusTooltip = locked
        ? "已定稿的版本不能再改状态"
        : invalidInputs
          ? "当前结果的输入已过期或缺失，请先重新生成或修复依赖"
          : undefined;

    if (!artifacts.length) return null;

    const changeStatus = async (action: "approve" | "lock") => {
        if (!version || invalidInputs) return;
        try {
            if (action === "approve") await approveVersion.mutateAsync(version.id);
            else await lockVersion.mutateAsync(version.id);
            message.success(action === "approve" ? "已采用当前版本" : "已将当前版本定稿");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        }
    };

    return (
        <Surface as="section" level="panel" radius="md" hairline lift inset="4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <Text as="h2" variant="heading" tone="ink">
                        创作稿件
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                        AI 或你保存的内容会出现在这里，每次修改都会保留历史版本。
                    </Text>
                </div>
                <Tag className="m-0">{artifacts.length} 份</Tag>
            </div>

            <div className="hide-scrollbar mt-4 flex gap-2 overflow-x-auto pb-1">
                {artifacts.map((artifact) => {
                    const itemFreshness = freshnessMap.get(artifact.id);
                    const itemMeta = itemFreshness
                        ? freshnessMeta(itemFreshness.status)
                        : null;
                    return (
                        <button
                            key={artifact.id}
                            type="button"
                            onClick={() => setSelectedId(artifact.id)}
                            aria-pressed={selectedId === artifact.id}
                            className={cn(
                                "relative min-w-44 rounded-[var(--r-sm)] border px-3 py-2.5 text-left transition-colors",
                                selectedId === artifact.id
                                    ? "border-[var(--hairline-strong)] bg-[var(--s-raised)]"
                                    : "border-[var(--hairline)] hover:bg-[var(--s-raised)]",
                            )}
                        >
                            {selectedId === artifact.id ? (
                                <span
                                    aria-hidden
                                    className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-action)]"
                                />
                            ) : null}
                            <div className="flex items-center gap-2">
                                <FileText className="size-4 shrink-0 text-[var(--s-faint)]" />
                                <Text as="span" variant="body" tone="ink" weight={500} truncate>
                                    {artifact.name}
                                </Text>
                            </div>
                            <Text variant="caption" tone="faint" className="mt-1 block">
                                {artifactKindLabel(artifact.kind)} · 第 {artifact.current_version?.version || 0} 版 ·{" "}
                                {artifactStatusLabel(artifact.current_version?.status)}
                            </Text>
                            {itemFreshness && itemMeta ? (
                                <Chip tone={itemMeta.tone} className="mt-1.5">
                                    {itemMeta.shortLabel}
                                </Chip>
                            ) : null}
                        </button>
                    );
                })}
            </div>

            {selected ? (
                <div className="mt-4 border-t border-[var(--hairline)] pt-4">
                    {selectedFreshness ? (
                        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-[var(--r-sm)] border border-[var(--hairline)] bg-[var(--s-raised)] px-3 py-2.5">
                            <StatusDot
                                tone={freshnessMeta(selectedFreshness.status).dotTone}
                            />
                            <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                    <Text
                                        as="span"
                                        variant="body"
                                        tone="ink"
                                        weight={600}
                                    >
                                        {freshnessMeta(selectedFreshness.status).label}
                                    </Text>
                                    <Chip
                                        tone={freshnessMeta(selectedFreshness.status).tone}
                                    >
                                        {freshnessMeta(selectedFreshness.status).shortLabel}
                                    </Chip>
                                </div>
                                <Text
                                    as="p"
                                    variant="caption"
                                    tone="muted"
                                    className="mt-0.5 leading-5"
                                >
                                    {freshnessReason(
                                        selectedFreshness.status,
                                        selectedFreshness.reason,
                                    )}
                                </Text>
                            </div>
                            <Link
                                href={versionsHref(
                                    projectId,
                                    selected.id,
                                    selected.unit_id,
                                )}
                            >
                                <Button size="sm">查看版本</Button>
                            </Link>
                        </div>
                    ) : null}

                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                            <Text as="h3" variant="body" tone="ink" weight={600} truncate>
                                {selected.name}
                            </Text>
                            <Text variant="caption" tone="faint" className="mt-0.5 block">
                                {artifactKindLabel(selected.kind)} · 第 {version?.version || 0} 版 ·{" "}
                                {artifactStatusLabel(version?.status)}
                            </Text>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <Button size="sm" icon={<FileText className="size-3.5" />} onClick={() => setEditorOpen(true)}>
                                编辑源码
                            </Button>
                            <Tooltip title={statusTooltip}>
                                <span>
                                    <Button
                                        size="sm"
                                        disabled={statusDisabled}
                                        icon={<Check className="size-3.5" />}
                                        loading={approveVersion.isPending}
                                        onClick={() => void changeStatus("approve")}
                                    >
                                        采用版本
                                    </Button>
                                </span>
                            </Tooltip>
                            <Tooltip title={locked ? "已定稿" : statusTooltip || "定稿后内容不再变动"}>
                                <span>
                                    <Button
                                        size="sm"
                                        disabled={statusDisabled}
                                        icon={<Lock className="size-3.5" />}
                                        loading={lockVersion.isPending}
                                        onClick={() => void changeStatus("lock")}
                                    >
                                        定稿
                                    </Button>
                                </span>
                            </Tooltip>
                        </div>
                    </div>
                    <StoryRenderer kind={selected.kind} payload={version?.payload || {}} onRewrite={rewriteBlock} />
                </div>
            ) : null}

            <ArtifactEditorModal
                open={editorOpen}
                projectId={projectId}
                artifact={selected}
                onClose={() => setEditorOpen(false)}
            />
        </Surface>
    );
}
