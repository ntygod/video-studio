"use client";

import { Check, ExternalLink, Film, Play, Settings2, Sparkles } from "lucide-react";
import Link from "next/link";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { jobTypeLabel } from "@/features/workspace/lib/labels";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { isJobActive, mediaUrl } from "@/services/api";
import { useCompileTimeline, useHasLlm, useJobs, useRenderTimeline, useStartGeneration } from "@/services/queries";
import { progressPercent } from "@/shared/lib/format";
import { cn } from "@/shared/lib/utils";
import { Button, Progress, Surface, Tag, Text, Tooltip, useApp } from "@/shared/ui";

/** 让 AI 产出剪辑方案的指令。要求只引用上下文里真实存在的素材 id，避免虚构。 */
const EDIT_PLAN_PROMPT =
    "你是通用 AI 制作助手。根据项目内容和已有素材输出 JSON 对象，必须包含 decisions 数组。" +
    "每条 decision 包含 asset_id、source_in、source_out、duration、speed、hold_after、audio、reason；" +
    "只引用上下文里已有的素材 id，不要虚构素材。没有可用素材时返回空 decisions。";

function ChecklistItem({ done, label, value }: { done: boolean; label: string; value: string }) {
    return (
        <div
            className={cn(
                "flex items-center gap-2 rounded-[var(--r-sm)] border px-3 py-2 text-caption",
                done
                    ? "border-[var(--hairline-strong)] text-[var(--s-ink)]"
                    : "border-[var(--hairline)] text-[var(--s-faint)]",
            )}
        >
            {done ? <Check className="size-3.5 shrink-0 text-[var(--s-ink)]" /> : <span className="size-3.5 shrink-0" />}
            <span className="font-medium">{label}</span>
            <span className="ml-auto">{value}</span>
        </div>
    );
}

/**
 * 画布 · 成片。
 * <p>
 * 两步：先让 AI 依据素材与内容生成剪辑方案，再编译时间线并提交渲染。
 * P4 会在这里换成真正的时间线轨道与播放器。
 */
export function ProduceView() {
    const { message } = useApp();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { project, units, assets, hasEditPlan, contentArtifacts, hrefForMedia } = useProduceContext();
    const hasLlm = useHasLlm();
    const toggleDock = useWorkspaceStore((state) => state.toggleDock);
    const dockExpanded = useWorkspaceStore((state) => state.dockExpanded);

    const startGeneration = useStartGeneration(projectId);
    const compileTimeline = useCompileTimeline(projectId);
    const renderTimeline = useRenderTimeline(projectId);
    const jobsQuery = useJobs(projectId);

    const renderReady = assets.length > 0 && hasEditPlan;
    const busy = startGeneration.isPending || compileTimeline.isPending || renderTimeline.isPending;
    const activeRenderJob = (jobsQuery.data || []).find(
        (job) => job.job_type.includes("render") && isJobActive(job),
    );
    const latestRender = [...assets]
        .filter((asset) => asset.kind === "render")
        .sort((a, b) => b.created_at - a.created_at)[0];

    /** 提交任务后把任务坞展开，让用户看到进度而不是只弹个 toast。 */
    const revealDock = () => {
        if (!dockExpanded) toggleDock();
    };

    const generatePlan = async () => {
        if (!project) return;
        if (!hasLlm) {
            message.warning("请先在模型设置中启用一个 AI 模型");
            return;
        }
        try {
            await startGeneration.mutateAsync({
                capability: "llm",
                schema_id: "open/edit_plan@1",
                artifact_kind: "edit_plan",
                artifact_name: "制作方案",
                prompt: EDIT_PLAN_PROMPT,
                context: {
                    brief: project.brief,
                    units,
                    assets: assets.map((asset) => ({
                        id: asset.id,
                        kind: asset.kind,
                        name: asset.name,
                        uri: asset.uri,
                        mime_type: asset.mime_type,
                    })),
                    artifacts: contentArtifacts.map((artifact) => ({
                        id: artifact.id,
                        kind: artifact.kind,
                        payload: artifact.current_version?.payload,
                    })),
                },
            });
            message.success("已提交制作方案任务");
            revealDock();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "任务提交失败");
        }
    };

    const produce = async () => {
        if (!renderReady) {
            message.warning("生成成片前需要至少一份素材和一份制作方案");
            return;
        }
        try {
            const compiled = await compileTimeline.mutateAsync({ unit_id: selectedUnitId });
            await renderTimeline.mutateAsync({ timeline: compiled.timeline, name: "项目成片" });
            message.success("已提交渲染任务");
            revealDock();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "渲染任务提交失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1120px] px-5 py-6 md:px-7">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <Text as="h1" variant="heading" tone="ink">
                        交付室
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                        检查制作条件，生成剪辑方案，编译时间线并渲染最终产物。
                    </Text>
                </div>
                <Tooltip title={renderReady ? "编译时间线并渲染" : "需要素材和制作方案"}>
                    <span>
                        <Button
                            variant="primary"
                            disabled={!renderReady || busy}
                            icon={<Play className="size-4" />}
                            loading={compileTimeline.isPending || renderTimeline.isPending}
                            onClick={() => void produce()}
                        >
                            开始渲染
                        </Button>
                    </span>
                </Tooltip>
            </div>

            <div className="grid gap-4 lg:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.15fr)]">
                <Surface
                    as="section"
                    level="canvas"
                    radius="md"
                    className="relative min-h-[420px] overflow-hidden border border-[var(--hairline)]"
                >
                    {latestRender && latestRender.mime_type.startsWith("video/") ? (
                        <video src={mediaUrl(latestRender.uri)} controls className="absolute inset-0 h-full w-full object-cover" />
                    ) : latestRender && latestRender.mime_type.startsWith("image/") ? (
                        <img src={mediaUrl(latestRender.uri)} alt={latestRender.name} className="absolute inset-0 h-full w-full object-cover" />
                    ) : (
                        <>
                            <div className="studio-project-cover absolute inset-0 opacity-90" data-tone="3" />
                            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-5 pt-20 text-white">
                                <Text as="div" variant="title" className="!text-white">
                                    {project?.title || "项目成片"}
                                </Text>
                                <Text as="div" variant="caption" className="mt-1 !text-white/80">
                                    {project?.brief.concept || "完成制作检查后即可生成预览"}
                                </Text>
                            </div>
                        </>
                    )}
                    <span className="absolute right-3 top-3 rounded-full bg-black/45 px-2.5 py-1 text-caption text-white backdrop-blur-md">
                        9:16 · 项目预览
                    </span>
                </Surface>

                <div className="space-y-4">
                    <Surface as="section" level="panel" radius="md" hairline lift inset="4">
                        <div className="flex items-center gap-2">
                            <Text as="h2" variant="heading" tone="ink" className="min-w-0 flex-1">
                                制作检查
                            </Text>
                            <Tag color={renderReady ? "green" : "orange"} className="m-0">
                                {renderReady ? "可以渲染" : "仍需准备"}
                            </Tag>
                        </div>

                        <div className="mt-4 grid gap-2 sm:grid-cols-2">
                            <ChecklistItem done={hasLlm} label="创作模型" value={hasLlm ? "已连接" : "未配置"} />
                            <ChecklistItem done={assets.length > 0} label="项目素材" value={assets.length > 0 ? `${assets.length} 份` : "未准备"} />
                            <ChecklistItem done={hasEditPlan} label="剪辑方案" value={hasEditPlan ? "已准备" : "未准备"} />
                            <ChecklistItem done={Boolean(latestRender)} label="最近成片" value={latestRender ? "已有产物" : "尚未渲染"} />
                        </div>

                        <div className="mt-4 flex flex-wrap gap-2 border-t border-[var(--hairline)] pt-4">
                            <Button
                                disabled={!hasLlm || assets.length === 0}
                                icon={<Sparkles className="size-4" />}
                                loading={startGeneration.isPending}
                                onClick={() => void generatePlan()}
                            >
                                {hasEditPlan ? "重新生成剪辑方案" : "生成剪辑方案"}
                            </Button>
                            <Button disabled icon={<Settings2 className="size-4" />}>交付设置</Button>
                            {assets.length === 0 ? (
                                <Link href={hrefForMedia}>
                                    <Button variant="ghost">先添加素材</Button>
                                </Link>
                            ) : null}
                        </div>
                    </Surface>

                    {activeRenderJob ? (
                        <Surface as="section" level="raised" radius="md" inset="3" className="border border-[var(--s-action-line)]">
                            <div className="flex items-center gap-2">
                                <span className="size-1.5 animate-pulse rounded-full bg-[var(--s-action)]" />
                                <Text variant="label" tone="ink" weight={500} className="min-w-0 flex-1">
                                    {jobTypeLabel(activeRenderJob.job_type)}
                                </Text>
                                <Text variant="mono" tone="ink">
                                    {progressPercent(activeRenderJob.progress)}%
                                </Text>
                            </div>
                            <Progress value={progressPercent(activeRenderJob.progress) / 100} className="mt-2" />
                            <Text variant="caption" tone="faint" className="mt-2 block">
                                渲染任务已进入持久化队列，可在底部任务坞或任务中心继续查看。
                            </Text>
                        </Surface>
                    ) : null}

                    {latestRender ? (
                        <Surface as="section" level="panel" radius="md" hairline inset="3">
                            <div className="flex items-center gap-3">
                                <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-[var(--s-muted)]">
                                    <Film className="size-4" />
                                </span>
                                <div className="min-w-0 flex-1">
                                    <Text variant="label" tone="ink" weight={500} truncate className="block">
                                        {latestRender.name || "项目成片"}
                                    </Text>
                                    <Text variant="caption" tone="faint" className="mt-0.5 block">
                                        最近一次渲染产物
                                    </Text>
                                </div>
                                <a href={mediaUrl(latestRender.uri)} target="_blank" rel="noreferrer">
                                    <Button size="sm" icon={<ExternalLink className="size-3.5" />}>
                                        打开
                                    </Button>
                                </a>
                            </div>
                        </Surface>
                    ) : null}
                </div>
            </div>
        </div>
    );
}

/** 汇总本视图需要的上下文，避免在组件里散落多个 hook 调用。 */
function useProduceContext() {
    const data = useWorkspaceData();
    const { hrefFor } = useWorkspaceRoute();
    return { ...data, hrefForMedia: hrefFor("media") };
}
