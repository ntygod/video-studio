"use client";

import { useEffect, useMemo, useState } from "react";
import { History, RotateCcw } from "lucide-react";
import { useSearchParams } from "next/navigation";

import { artifactKindLabel, artifactStatusLabel } from "@/features/workspace/lib/labels";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useArtifactVersions, useRestoreArtifactVersion, useVersionDiff } from "@/services/queries";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { cn } from "@/shared/lib/utils";
import { Button, Select, Spin, Surface, Tag, Text, Tooltip, useApp } from "@/shared/ui";

function DiffValue({ value }: { value: unknown }) {
    if (value === null || value === undefined) return <span className="text-[var(--s-faint)]">—</span>;
    if (typeof value === "object") {
        return <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-caption text-[var(--s-muted)]">{JSON.stringify(value, null, 2)}</pre>;
    }
    return <span className="whitespace-pre-wrap break-all text-label">{String(value)}</span>;
}

/**
 * 版本视图（T4.F2）：左侧版本列表，右侧与当前版本的结构化 diff，支持回滚。
 */
export function VersionsView() {
    const { message } = useApp();
    const searchParams = useSearchParams();
    const requestedArtifactId = searchParams.get("artifact");
    const { projectId, reviewableArtifacts } = useWorkspaceData();
    const [artifactId, setArtifactId] = useState<string | null>(null);
    const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

    useEffect(() => {
        setArtifactId((current) => {
            if (
                requestedArtifactId &&
                reviewableArtifacts.some(
                    (item) => item.id === requestedArtifactId,
                )
            ) {
                return requestedArtifactId;
            }
            if (current && reviewableArtifacts.some((item) => item.id === current)) return current;
            return reviewableArtifacts[0]?.id ?? null;
        });
    }, [requestedArtifactId, reviewableArtifacts]);

    const versionsQuery = useArtifactVersions(artifactId);
    const versions = useMemo(() => versionsQuery.data || [], [versionsQuery.data]);
    const currentVersionId = versions[0]?.id || null;

    useEffect(() => {
        setSelectedVersionId((current) => {
            if (current && versions.some((item) => item.id === current)) return current;
            return versions[0]?.id ?? null;
        });
    }, [versions]);

    const diffQuery = useVersionDiff(currentVersionId, selectedVersionId);
    const restore = useRestoreArtifactVersion(projectId);
    const selectedVersion = versions.find((item) => item.id === selectedVersionId) || null;

    const restoreVersion = async (versionId: string) => {
        if (!artifactId) return;
        try {
            await restore.mutateAsync({ artifactId, versionId });
            message.success("已回滚并追加新版本");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "回滚失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1100px] px-5 py-6 md:px-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <Text as="h1" variant="heading" tone="ink">
                        版本与审阅
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-0.5">
                        对比任意两个版本并回滚；回滚会追加新版本，历史永不删除。
                    </Text>
                </div>
                <Select
                    size="small"
                    className="min-w-[220px]"
                    placeholder="选择稿件"
                    value={artifactId || undefined}
                    onChange={setArtifactId}
                    options={reviewableArtifacts.map((artifact) => ({
                        value: artifact.id,
                        label: `${artifact.name}（${artifactKindLabel(artifact.kind)}）`,
                    }))}
                />
            </div>

            {!artifactId || !reviewableArtifacts.length ? (
                <div className="mt-10">
                    <EmptyState title="还没有创作稿件" description="先在故事视图让 AI 生成内容。" />
                </div>
            ) : versionsQuery.isError ? (
                <ErrorPanel title="版本加载失败" message={versionsQuery.error.message} onRetry={() => void versionsQuery.refetch()} />
            ) : versionsQuery.isLoading ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : (
                <div className="mt-5 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
                    <Surface as="aside" level="panel" radius="md" hairline lift inset="3">
                        <div className="mb-2 flex items-center gap-2 px-1 text-caption font-semibold text-[var(--s-ink)]">
                            <History className="size-3.5" />
                            版本历史（{versions.length}）
                        </div>
                        <div className="space-y-1">
                            {versions.map((version, index) => {
                                const current = index === 0;
                                const active = version.id === selectedVersionId;
                                return (
                                    <div
                                        key={version.id}
                                        role="button"
                                        tabIndex={0}
                                        aria-pressed={active}
                                        onClick={() => setSelectedVersionId(version.id)}
                                        onKeyDown={(event) => {
                                            if (event.key === "Enter" || event.key === " ") setSelectedVersionId(version.id);
                                        }}
                                        className={cn("relative rounded-[var(--r-sm)] border p-2.5 transition-colors", active ? "border-[var(--hairline-strong)] bg-[var(--s-raised)]" : "border-transparent hover:bg-[var(--s-raised)]")}
                                    >
                                        {active ? <span aria-hidden className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-action)]" /> : null}
                                        <div className="flex items-center gap-2">
                                            <span className="text-label font-semibold text-[var(--s-ink)]">v{version.version}</span>
                                            {current ? (
                                                <Tag color="green" className="m-0 text-caption">
                                                    当前
                                                </Tag>
                                            ) : null}
                                            <span className="ml-auto text-caption text-[var(--s-faint)]">{version.source === "ai" ? "AI" : version.source === "system" ? "系统" : "用户"}</span>
                                        </div>
                                        <div className="mt-1 truncate text-caption text-[var(--s-faint)]">
                                            {artifactStatusLabel(version.status)} · {version.note || "无备注"}
                                        </div>
                                        {!current ? (
                                            <Tooltip title="以该版本内容追加新版本">
                                                <Button
                                                    size="sm"
                                                    variant="ghost"
                                                    className="!mt-1 !h-6 !px-1.5 !text-caption"
                                                    icon={<RotateCcw className="size-3" />}
                                                    loading={restore.isPending}
                                                    onClick={(event) => {
                                                        event.stopPropagation();
                                                        void restoreVersion(version.id);
                                                    }}
                                                >
                                                    回滚
                                                </Button>
                                            </Tooltip>
                                        ) : null}
                                    </div>
                                );
                            })}
                        </div>
                    </Surface>

                    <Surface as="section" level="panel" radius="md" hairline lift inset="4" className="min-w-0">
                        <div className="mb-3 flex items-center justify-between">
                            <Text as="h2" variant="body" tone="ink" weight={600}>
                                {selectedVersion ? `v${selectedVersion.version} 与当前版本对比` : "选择版本"}
                            </Text>
                            <span className="text-caption text-[var(--s-faint)]">{selectedVersion ? `创建于 ${new Date(selectedVersion.created_at * 1000).toLocaleString()}` : ""}</span>
                        </div>
                        {diffQuery.isLoading ? (
                            <div className="flex justify-center py-12">
                                <Spin size="small" />
                            </div>
                        ) : diffQuery.isError ? (
                            <ErrorPanel title="Diff 失败" message={diffQuery.error.message} onRetry={() => void diffQuery.refetch()} />
                        ) : !diffQuery.data || !diffQuery.data.field_diffs.length ? (
                            <div className="py-12 text-center text-label text-[var(--s-faint)]">两个版本内容一致</div>
                        ) : (
                            <div className="divide-y divide-[var(--hairline)]">
                                {diffQuery.data.field_diffs.map((diff) => (
                                    <div key={`${diff.path}:${diff.op}`} className="grid gap-2 py-3 sm:grid-cols-[120px_minmax(0,1fr)_minmax(0,1fr)]">
                                        <div className="flex flex-col gap-1">
                                            <code className="break-all text-caption text-[var(--s-ink)]">{diff.path}</code>
                                            <Tag color={diff.op === "add" ? "green" : diff.op === "remove" ? "red" : "orange"} className="m-0 w-fit text-caption">
                                                {diff.op === "add" ? "新增" : diff.op === "remove" ? "删除" : "修改"}
                                            </Tag>
                                        </div>
                                        <div className="min-w-0 rounded bg-[var(--s-raised)] p-2">
                                            <div className="mb-1 text-caption text-[var(--s-faint)]">之前</div>
                                            <DiffValue value={diff.before} />
                                        </div>
                                        <div className="min-w-0 rounded bg-[var(--s-raised)] p-2">
                                            <div className="mb-1 text-caption text-[var(--s-faint)]">之后</div>
                                            <DiffValue value={diff.after} />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </Surface>
                </div>
            )}
        </div>
    );
}
