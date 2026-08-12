"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    GitBranch,
    RefreshCw,
    Sparkles,
} from "lucide-react";

import { RegenerationPlanModal } from "@/features/workspace/components/regeneration-plan-modal";
import type {
    ArtifactImpactItem,
    ProjectArtifactFreshnessItem,
} from "@/services/api";
import {
    useArtifactImpact,
    useProjectArtifactFreshness,
    useRegenerateArtifact,
} from "@/services/queries";
import {
    actionableFreshnessCount,
    freshnessMeta,
    freshnessReason,
    sortFreshnessItems,
} from "@/features/workspace/lib/freshness";
import {
    Button,
    Chip,
    Drawer,
    Spin,
    StatusDot,
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

function ImpactRow({ projectId, item }: { projectId: string; item: ArtifactImpactItem }) {
    const meta = freshnessMeta(item.freshness.status);
    return (
        <Link
            href={versionsHref(projectId, item.artifact_id)}
            className="flex items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 transition-colors hover:bg-[var(--s-raised)]"
        >
            <StatusDot tone={meta.dotTone} />
            <span className="min-w-0 flex-1 truncate text-label text-[var(--s-text)]">
                {item.artifact_name}
            </span>
            <span className="shrink-0 text-caption text-[var(--s-faint)]">
                {meta.shortLabel}
            </span>
        </Link>
    );
}

function ImpactDisclosure({ projectId, artifactId }: { projectId: string; artifactId: string }) {
    const [expanded, setExpanded] = useState(false);
    const query = useArtifactImpact(artifactId, expanded);
    return (
        <div className="mt-2">
            <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setExpanded((value) => !value)}
                className="inline-flex items-center gap-1 text-caption text-[var(--s-muted)] transition-colors hover:text-[var(--s-ink)]"
            >
                {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                查看后续影响
            </button>
            {expanded ? (
                <div className="mt-2 rounded-[var(--r-sm)] border border-[var(--hairline)] p-1.5">
                    {query.isLoading ? (
                        <div className="flex items-center justify-center gap-2 py-3 text-caption text-[var(--s-faint)]">
                            <Spin size="small" />
                            读取影响范围…
                        </div>
                    ) : query.isError ? (
                        <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                            <span className="text-caption text-[var(--s-danger)]">影响范围读取失败</span>
                            <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3" />} onClick={() => void query.refetch()}>
                                重试
                            </Button>
                        </div>
                    ) : query.data?.length ? (
                        <div className="space-y-0.5">
                            {query.data.map((impact) => (
                                <ImpactRow key={impact.artifact_id} projectId={projectId} item={impact} />
                            ))}
                        </div>
                    ) : (
                        <p className="px-2 py-2 text-caption text-[var(--s-faint)]">当前没有继续依赖它的产物。</p>
                    )}
                </div>
            ) : null}
        </div>
    );
}

function FreshnessItem({
    projectId,
    item,
    regenerating,
    onRegenerate,
    onPlan,
}: {
    projectId: string;
    item: ProjectArtifactFreshnessItem;
    regenerating: boolean;
    onRegenerate: (artifactId: string) => void;
    onPlan: (item: ProjectArtifactFreshnessItem) => void;
}) {
    const meta = freshnessMeta(item.status);
    const invalidInputCount = item.stale_from_version_ids.length + item.blocked_by_asset_ids.length;
    return (
        <article className="px-4 py-4">
            <div className="flex items-start gap-3">
                <div className="pt-1"><StatusDot tone={meta.dotTone} /></div>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Text as="h3" variant="body" tone="ink" weight={600} truncate>{item.name}</Text>
                        <Chip tone={meta.tone}>{meta.shortLabel}</Chip>
                    </div>
                    <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                        {freshnessReason(item.status, item.reason)}
                    </Text>
                    {invalidInputCount ? (
                        <Text as="p" variant="caption" tone="faint" className="mt-1">
                            关联 {invalidInputCount} 个已变化或缺失的输入
                        </Text>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        {item.status === "stale" ? (
                            <Button size="sm" icon={<Sparkles className="size-3.5" />} loading={regenerating} onClick={() => onRegenerate(item.artifact_id)}>
                                只重新生成此项
                            </Button>
                        ) : null}
                        <Button size="sm" variant="secondary" icon={<GitBranch className="size-3.5" />} onClick={() => onPlan(item)}>
                            级联修复
                        </Button>
                        <Link href={versionsHref(projectId, item.artifact_id, item.unit_id)}>
                            <Button size="sm" variant="ghost">打开版本</Button>
                        </Link>
                    </div>
                    <ImpactDisclosure projectId={projectId} artifactId={item.artifact_id} />
                </div>
            </div>
        </article>
    );
}

export function FreshnessCenter({ projectId }: { projectId: string }) {
    const { message } = useApp();
    const [open, setOpen] = useState(false);
    const [planRoot, setPlanRoot] = useState<ProjectArtifactFreshnessItem | null>(null);
    const query = useProjectArtifactFreshness(projectId);
    const regenerate = useRegenerateArtifact(projectId);
    const count = actionableFreshnessCount(query.data);
    const items = useMemo(() => sortFreshnessItems(query.data?.items || []), [query.data?.items]);

    const startRegeneration = async (artifactId: string) => {
        try {
            const job = await regenerate.mutateAsync(artifactId);
            message.success(`重新生成任务已创建：${job.id.slice(0, 8)}`);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "重新生成任务创建失败");
        }
    };

    if (!count && !query.isError && !planRoot) return null;

    return (
        <>
            <Tooltip title={query.isError ? "内容状态读取失败" : `${count} 份内容需要处理`}>
                <Button size="sm" variant="ghost" aria-label="打开内容状态" icon={<AlertTriangle className="size-4" />} onClick={() => setOpen(true)}>
                    <span className="hidden 2xl:inline">内容状态</span>
                    <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--s-raised)] px-1 text-caption text-[var(--s-ink)]">
                        {query.isError ? "!" : count}
                    </span>
                </Button>
            </Tooltip>

            <Drawer
                title={<div><Text as="span" variant="body" tone="ink" weight={600}>内容状态</Text><Text as="p" variant="caption" tone="faint" className="mt-0.5">先处理阻塞，再按依赖顺序修复过期内容。</Text></div>}
                placement="right"
                size={480}
                open={open}
                onClose={() => setOpen(false)}
                styles={{ body: { padding: 0 } }}
            >
                {query.isError ? (
                    <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
                        <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                        <Text variant="body" tone="ink">内容状态读取失败</Text>
                        <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={() => void query.refetch()}>重新读取</Button>
                    </div>
                ) : query.isLoading && !query.data ? (
                    <div className="flex justify-center py-16"><Spin size="large" /></div>
                ) : items.length ? (
                    <div className="divide-y divide-[var(--hairline)]">
                        {items.map((item) => (
                            <FreshnessItem
                                key={item.artifact_id}
                                projectId={projectId}
                                item={item}
                                regenerating={regenerate.isPending && regenerate.variables === item.artifact_id}
                                onRegenerate={(artifactId) => void startRegeneration(artifactId)}
                                onPlan={setPlanRoot}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="px-5 py-12 text-center"><Text variant="body" tone="ink">当前内容都是最新的</Text></div>
                )}
            </Drawer>

            <RegenerationPlanModal
                projectId={projectId}
                root={planRoot}
                open={Boolean(planRoot)}
                onClose={() => setPlanRoot(null)}
            />
        </>
    );
}
