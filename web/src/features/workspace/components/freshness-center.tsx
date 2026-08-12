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
import {
    regenerationPlanMeta,
} from "@/features/workspace/lib/regeneration-plan";
import type {
    ArtifactImpactItem,
    ProjectArtifactFreshnessItem,
    RegenerationPlan,
} from "@/services/api";
import {
    useArtifactImpact,
    useProjectArtifactFreshness,
    useRegenerateArtifact,
    useRegenerationPlans,
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

function ImpactRow({
    projectId,
    item,
}: {
    projectId: string;
    item: ArtifactImpactItem;
}) {
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

function ImpactDisclosure({
    projectId,
    artifactId,
}: {
    projectId: string;
    artifactId: string;
}) {
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
                {expanded ? (
                    <ChevronDown className="size-3.5" />
                ) : (
                    <ChevronRight className="size-3.5" />
                )}
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
                            <span className="text-caption text-[var(--s-danger)]">
                                影响范围读取失败
                            </span>
                            <Button
                                size="sm"
                                variant="ghost"
                                icon={<RefreshCw className="size-3" />}
                                onClick={() => void query.refetch()}
                            >
                                重试
                            </Button>
                        </div>
                    ) : query.data?.length ? (
                        <div className="space-y-0.5">
                            {query.data.map((impact) => (
                                <ImpactRow
                                    key={impact.artifact_id}
                                    projectId={projectId}
                                    item={impact}
                                />
                            ))}
                        </div>
                    ) : (
                        <p className="px-2 py-2 text-caption text-[var(--s-faint)]">
                            当前没有继续依赖它的产物。
                        </p>
                    )}
                </div>
            ) : null}
        </div>
    );
}

function PlanSummaryRow({
    plan,
    onOpen,
}: {
    plan: RegenerationPlan;
    onOpen: () => void;
}) {
    const meta = regenerationPlanMeta(plan.status);
    const completed = Number(plan.summary.completed || 0);
    const total = Number(plan.summary.total || 0);
    return (
        <button
            type="button"
            onClick={onOpen}
            className="flex w-full items-center gap-3 rounded-[var(--r-sm)] px-2 py-2 text-left transition-colors hover:bg-[var(--s-raised)]"
        >
            <StatusDot tone={meta.dotTone} />
            <span className="min-w-0 flex-1">
                <Text
                    as="span"
                    variant="body"
                    tone="ink"
                    weight={500}
                    className="block"
                    truncate
                >
                    计划 {plan.id.slice(0, 8)}
                </Text>
                <Text
                    as="span"
                    variant="caption"
                    tone="faint"
                    className="mt-0.5 block"
                >
                    {completed}/{total || "—"} 步 · {new Date(
                        plan.created_at * 1000,
                    ).toLocaleString()}
                </Text>
            </span>
            <Chip tone={meta.tone}>{meta.label}</Chip>
        </button>
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
    const invalidInputCount =
        item.stale_from_version_ids.length +
        item.blocked_by_asset_ids.length;
    return (
        <article className="px-4 py-4">
            <div className="flex items-start gap-3">
                <div className="pt-1">
                    <StatusDot tone={meta.dotTone} />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Text
                            as="h3"
                            variant="body"
                            tone="ink"
                            weight={600}
                            truncate
                        >
                            {item.name}
                        </Text>
                        <Chip tone={meta.tone}>{meta.shortLabel}</Chip>
                    </div>
                    <Text
                        as="p"
                        variant="caption"
                        tone="muted"
                        className="mt-1 leading-5"
                    >
                        {freshnessReason(item.status, item.reason)}
                    </Text>
                    {invalidInputCount ? (
                        <Text
                            as="p"
                            variant="caption"
                            tone="faint"
                            className="mt-1"
                        >
                            关联 {invalidInputCount} 个已变化或缺失的输入
                        </Text>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        {item.status === "stale" ? (
                            <Button
                                size="sm"
                                icon={<Sparkles className="size-3.5" />}
                                loading={regenerating}
                                onClick={() => onRegenerate(item.artifact_id)}
                            >
                                只重新生成此项
                            </Button>
                        ) : null}
                        <Button
                            size="sm"
                            variant="secondary"
                            icon={<GitBranch className="size-3.5" />}
                            onClick={() => onPlan(item)}
                        >
                            级联修复
                        </Button>
                        <Link
                            href={versionsHref(
                                projectId,
                                item.artifact_id,
                                item.unit_id,
                            )}
                        >
                            <Button size="sm" variant="ghost">
                                打开版本
                            </Button>
                        </Link>
                    </div>
                    <ImpactDisclosure
                        projectId={projectId}
                        artifactId={item.artifact_id}
                    />
                </div>
            </div>
        </article>
    );
}

export function FreshnessCenter({
    projectId,
}: {
    projectId: string;
}) {
    const { message } = useApp();
    const [open, setOpen] = useState(false);
    const [planRoot, setPlanRoot] =
        useState<ProjectArtifactFreshnessItem | null>(null);
    const [existingPlanId, setExistingPlanId] = useState<string | null>(
        null,
    );
    const query = useProjectArtifactFreshness(projectId);
    const plansQuery = useRegenerationPlans(projectId);
    const regenerate = useRegenerateArtifact(projectId);
    const count = actionableFreshnessCount(query.data);
    const items = useMemo(
        () => sortFreshnessItems(query.data?.items || []),
        [query.data?.items],
    );
    const plans = plansQuery.data || [];
    const attentionPlans = plans.filter((plan) =>
        ["draft", "running", "blocked", "failed"].includes(plan.status),
    );
    const recentPlans = plans.slice(0, 5);
    const badgeCount = count + attentionPlans.length;
    const hasHistory = recentPlans.length > 0;

    const startRegeneration = async (artifactId: string) => {
        try {
            const job = await regenerate.mutateAsync(artifactId);
            message.success(`重新生成任务已创建：${job.id.slice(0, 8)}`);
        } catch (error) {
            message.error(
                error instanceof Error
                    ? error.message
                    : "重新生成任务创建失败",
            );
        }
    };

    const openNewPlan = (item: ProjectArtifactFreshnessItem) => {
        setExistingPlanId(null);
        setPlanRoot(item);
    };
    const openExistingPlan = (planId: string) => {
        setPlanRoot(null);
        setExistingPlanId(planId);
    };
    const closePlan = () => {
        setPlanRoot(null);
        setExistingPlanId(null);
    };

    if (
        !count &&
        !query.isError &&
        !plansQuery.isError &&
        !hasHistory &&
        !planRoot &&
        !existingPlanId
    ) {
        return null;
    }

    const tooltipTitle =
        query.isError || plansQuery.isError
            ? "内容或修复计划状态读取失败"
            : badgeCount
              ? `${count} 份内容、${attentionPlans.length} 个计划需要关注`
              : "查看修复计划历史";

    return (
        <>
            <Tooltip title={tooltipTitle}>
                <Button
                    size="sm"
                    variant="ghost"
                    aria-label="打开内容状态与修复计划"
                    icon={<AlertTriangle className="size-4" />}
                    onClick={() => setOpen(true)}
                >
                    <span className="hidden 2xl:inline">内容状态</span>
                    <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--s-raised)] px-1 text-caption text-[var(--s-ink)]">
                        {query.isError || plansQuery.isError
                            ? "!"
                            : badgeCount || "·"}
                    </span>
                </Button>
            </Tooltip>

            <Drawer
                title={
                    <div>
                        <Text as="span" variant="body" tone="ink" weight={600}>
                            内容状态
                        </Text>
                        <Text
                            as="p"
                            variant="caption"
                            tone="faint"
                            className="mt-0.5"
                        >
                            查看持久化修复计划，并按依赖顺序处理过期内容。
                        </Text>
                    </div>
                }
                placement="right"
                size={480}
                open={open}
                onClose={() => setOpen(false)}
                styles={{ body: { padding: 0 } }}
            >
                {plansQuery.isLoading && !plansQuery.data ? (
                    <div className="flex items-center justify-center gap-2 border-b border-[var(--hairline)] px-4 py-5 text-caption text-[var(--s-faint)]">
                        <Spin size="small" />
                        读取修复计划…
                    </div>
                ) : plansQuery.isError ? (
                    <div className="flex items-center justify-between gap-3 border-b border-[var(--hairline)] px-4 py-4">
                        <Text variant="caption" tone="danger">
                            修复计划读取失败
                        </Text>
                        <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void plansQuery.refetch()}
                        >
                            重试
                        </Button>
                    </div>
                ) : recentPlans.length ? (
                    <section className="border-b border-[var(--hairline)] px-2 py-3">
                        <div className="mb-1 flex items-center justify-between px-2">
                            <Text variant="label" tone="ink">
                                修复计划
                            </Text>
                            <Text variant="caption" tone="faint">
                                最近 {recentPlans.length} 个
                            </Text>
                        </div>
                        <div className="space-y-0.5">
                            {recentPlans.map((plan) => (
                                <PlanSummaryRow
                                    key={plan.id}
                                    plan={plan}
                                    onOpen={() => openExistingPlan(plan.id)}
                                />
                            ))}
                        </div>
                    </section>
                ) : null}

                <section>
                    <div className="border-b border-[var(--hairline)] px-4 py-3">
                        <Text variant="label" tone="ink">
                            待处理内容
                        </Text>
                    </div>
                    {query.isError ? (
                        <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
                            <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                            <Text variant="body" tone="ink">
                                内容状态读取失败
                            </Text>
                            <Button
                                size="sm"
                                icon={<RefreshCw className="size-3.5" />}
                                onClick={() => void query.refetch()}
                            >
                                重新读取
                            </Button>
                        </div>
                    ) : query.isLoading && !query.data ? (
                        <div className="flex justify-center py-16">
                            <Spin size="large" />
                        </div>
                    ) : items.length ? (
                        <div className="divide-y divide-[var(--hairline)]">
                            {items.map((item) => (
                                <FreshnessItem
                                    key={item.artifact_id}
                                    projectId={projectId}
                                    item={item}
                                    regenerating={
                                        regenerate.isPending &&
                                        regenerate.variables === item.artifact_id
                                    }
                                    onRegenerate={(artifactId) =>
                                        void startRegeneration(artifactId)
                                    }
                                    onPlan={openNewPlan}
                                />
                            ))}
                        </div>
                    ) : (
                        <div className="px-5 py-12 text-center">
                            <Text variant="body" tone="ink">
                                当前内容都是最新的
                            </Text>
                        </div>
                    )}
                </section>
            </Drawer>

            <RegenerationPlanModal
                projectId={projectId}
                root={planRoot}
                existingPlanId={existingPlanId}
                open={Boolean(planRoot || existingPlanId)}
                onClose={closePlan}
            />
        </>
    );
}
