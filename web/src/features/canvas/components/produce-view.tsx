"use client";

import { App, Button, Tooltip } from "antd";
import { Check, Play, Sparkles } from "lucide-react";
import Link from "next/link";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { useCompileTimeline, useHasLlm, useRenderTimeline, useStartGeneration } from "@/services/queries";
import { cn } from "@/shared/lib/utils";

/** 让 AI 产出剪辑方案的指令。要求只引用上下文里真实存在的素材 id，避免虚构。 */
const EDIT_PLAN_PROMPT =
    "你是通用 AI 制作助手。根据项目内容和已有素材输出 JSON 对象，必须包含 decisions 数组。" +
    "每条 decision 包含 asset_id、source_in、source_out、duration、speed、hold_after、audio、reason；" +
    "只引用上下文里已有的素材 id，不要虚构素材。没有可用素材时返回空 decisions。";

function ChecklistItem({ done, label, value }: { done: boolean; label: string; value: string }) {
    return (
        <div
            className={cn(
                "flex items-center gap-2 rounded-md border px-3 py-2 text-[11px]",
                done
                    ? "border-[var(--studio-action-line)] text-[var(--studio-ink)]"
                    : "border-[var(--studio-line)] text-[var(--studio-faint)]",
            )}
        >
            {done ? <Check className="size-3.5 shrink-0 text-[var(--studio-action)]" /> : <span className="size-3.5 shrink-0" />}
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
    const { message } = App.useApp();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { project, assets, hasEditPlan, contentArtifacts, hrefForMedia } = useProduceContext();
    const hasLlm = useHasLlm();
    const toggleDock = useWorkspaceStore((state) => state.toggleDock);
    const dockExpanded = useWorkspaceStore((state) => state.dockExpanded);

    const startGeneration = useStartGeneration(projectId);
    const compileTimeline = useCompileTimeline(projectId);
    const renderTimeline = useRenderTimeline(projectId);

    const renderReady = assets.length > 0 && hasEditPlan;
    const busy = startGeneration.isPending || compileTimeline.isPending || renderTimeline.isPending;

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
                    units: project.units,
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
        <div className="mx-auto w-full max-w-[900px] px-5 py-6 md:px-7">
            <section className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5">
                <h1 className="text-[15px] font-semibold text-[var(--studio-ink)]">生成成片</h1>
                <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                    先让 AI 根据内容和素材生成制作方案，准备好后即可编译时间线并渲染成片。
                </p>

                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    <ChecklistItem done={assets.length > 0} label="素材" value={assets.length > 0 ? `${assets.length} 份` : "未准备"} />
                    <ChecklistItem done={hasEditPlan} label="制作方案" value={hasEditPlan ? "已准备" : "未准备"} />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                        type="primary"
                        disabled={!hasLlm || assets.length === 0}
                        icon={<Sparkles className="size-4" />}
                        loading={startGeneration.isPending}
                        onClick={() => void generatePlan()}
                    >
                        生成制作方案
                    </Button>
                    <Tooltip title={renderReady ? "编译时间线并渲染" : "需要素材和制作方案"}>
                        <span>
                            <Button
                                disabled={!renderReady || busy}
                                icon={<Play className="size-4" />}
                                loading={compileTimeline.isPending || renderTimeline.isPending}
                                onClick={() => void produce()}
                            >
                                生成成片
                            </Button>
                        </span>
                    </Tooltip>
                    {assets.length === 0 ? (
                        <Link href={hrefForMedia}>
                            <Button type="link">先添加素材</Button>
                        </Link>
                    ) : null}
                </div>
            </section>
        </div>
    );
}

/** 汇总本视图需要的上下文，避免在组件里散落多个 hook 调用。 */
function useProduceContext() {
    const data = useWorkspaceData();
    const { hrefFor } = useWorkspaceRoute();
    return { ...data, hrefForMedia: hrefFor("media") };
}
