"use client";

import { useEffect, useState } from "react";
import { App, Button, Tag, Tooltip } from "antd";
import { Check, FileText, Lock } from "lucide-react";

import { ArtifactContentView } from "@/features/canvas/components/artifact-content-view";
import { ArtifactEditorModal } from "@/features/canvas/components/artifact-editor-modal";
import { artifactKindLabel, artifactStatusLabel } from "@/features/workspace/lib/labels";
import type { Artifact } from "@/services/api";
import { useApproveArtifactVersion, useLockArtifactVersion } from "@/services/queries";
import { cn } from "@/shared/lib/utils";

/**
 * 创作稿件列表与内容。
 * <p>
 * 上半部分是同一作用域下的稿件切换器，下半部分渲染选中稿件的当前版本。
 */
export function ArtifactPanel({ projectId, artifacts }: { projectId: string; artifacts: Artifact[] }) {
    const { message } = App.useApp();
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [editorOpen, setEditorOpen] = useState(false);

    const approveVersion = useApproveArtifactVersion(projectId);
    const lockVersion = useLockArtifactVersion(projectId);

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

    if (!artifacts.length) return null;

    const changeStatus = async (action: "approve" | "lock") => {
        if (!version) return;
        try {
            if (action === "approve") await approveVersion.mutateAsync(version.id);
            else await lockVersion.mutateAsync(version.id);
            message.success(action === "approve" ? "已采用当前版本" : "已将当前版本定稿");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        }
    };

    return (
        <section className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="text-[15px] font-semibold text-[var(--studio-ink)]">创作稿件</h2>
                    <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                        AI 或你保存的内容会出现在这里，每次修改都会保留历史版本。
                    </p>
                </div>
                <Tag className="m-0">{artifacts.length} 份</Tag>
            </div>

            <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {artifacts.map((artifact) => (
                    <button
                        key={artifact.id}
                        type="button"
                        onClick={() => setSelectedId(artifact.id)}
                        aria-pressed={selectedId === artifact.id}
                        className={cn(
                            "rounded-md border p-3 text-left transition-colors",
                            selectedId === artifact.id
                                ? "border-[var(--studio-action-line)] bg-[var(--studio-action-soft)]"
                                : "border-[var(--studio-line)] hover:border-[var(--studio-action-line)]",
                        )}
                    >
                        <div className="flex items-center gap-2">
                            <FileText className="size-4 shrink-0 text-[var(--studio-action)]" />
                            <span className="truncate text-[13px] font-medium text-[var(--studio-ink)]">{artifact.name}</span>
                        </div>
                        <div className="mt-1 text-[11px] text-[var(--studio-faint)]">
                            {artifactKindLabel(artifact.kind)} · 第 {artifact.current_version?.version || 0} 版 ·{" "}
                            {artifactStatusLabel(artifact.current_version?.status)}
                        </div>
                    </button>
                ))}
            </div>

            {selected ? (
                <div className="mt-4 border-t border-[var(--studio-line)] pt-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                            <h3 className="truncate text-[13px] font-semibold text-[var(--studio-ink)]">{selected.name}</h3>
                            <div className="mt-0.5 text-[11px] text-[var(--studio-faint)]">
                                {artifactKindLabel(selected.kind)} · 第 {version?.version || 0} 版 ·{" "}
                                {artifactStatusLabel(version?.status)}
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <Button size="small" icon={<FileText className="size-3.5" />} onClick={() => setEditorOpen(true)}>
                                编辑源码
                            </Button>
                            <Tooltip title={locked ? "已定稿的版本不能再改状态" : undefined}>
                                <span>
                                    <Button
                                        size="small"
                                        disabled={locked}
                                        icon={<Check className="size-3.5" />}
                                        loading={approveVersion.isPending}
                                        onClick={() => void changeStatus("approve")}
                                    >
                                        采用版本
                                    </Button>
                                </span>
                            </Tooltip>
                            <Tooltip title={locked ? "已定稿" : "定稿后内容不再变动"}>
                                <span>
                                    <Button
                                        size="small"
                                        disabled={locked}
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
                    <ArtifactContentView payload={version?.payload || {}} />
                </div>
            ) : null}

            <ArtifactEditorModal
                open={editorOpen}
                projectId={projectId}
                artifact={selected}
                onClose={() => setEditorOpen(false)}
            />
        </section>
    );
}
