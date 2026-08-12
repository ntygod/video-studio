"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
    AlertTriangle,
    Ban,
    CheckCircle2,
    GitBranch,
    LoaderCircle,
    Play,
    RefreshCw,
    Square,
    XCircle,
} from "lucide-react";

import {
    compatibleReplacementAsset,
    isRegenerationPlanTerminal,
    regenerationActionLabel,
    regenerationPlanHasUnresolvedInput,
    regenerationPlanMeta,
    regenerationPlanRetryBlocker,
    regenerationStepMeta,
} from "@/features/workspace/lib/regeneration-plan";
import type {
    AssetDependencyInput,
    ProjectArtifactFreshnessItem,
    RegenerationPlanStep,
    RegenerationPreviewStep,
} from "@/services/api";
import {
    useArtifactAssetDependencies,
    useAssets,
    useCancelRegenerationPlan,
    useCreateRegenerationPlan,
    usePreviewRegenerationCascade,
    useRegenerationPlan,
    useRetryRegenerationPlan,
    useSetRegenerationPlanStepInput,
    useStartRegenerationPlan,
} from "@/services/queries";
import {
    Button,
    Chip,
    Modal,
    Select,
    Spin,
    StatusDot,
    Surface,
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

function statusIcon(status: string) {
    if (status === "succeeded" || status === "skipped") {
        return <CheckCircle2 className="size-4" />;
    }
    if (status === "failed" || status === "blocked") {
        return <XCircle className="size-4" />;
    }
    if (status === "canceled") {
        return <Ban className="size-4" />;
    }
    if (status === "running" || status === "queued") {
        return <LoaderCircle className="size-4 animate-spin" />;
    }
    return <Square className="size-4" />;
}

function PreviewStepCard({
    projectId,
    step,
    index,
}: {
    projectId: string;
    step: RegenerationPreviewStep;
    index: number;
}) {
    const meta = regenerationStepMeta(step.execution_state);
    return (
        <Surface level="raised" radius="sm" hairline inset="3">
            <div className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--s-panel)] text-caption text-[var(--s-faint)]">
                    {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusDot tone={meta.dotTone} />
                        <Text variant="body" tone="ink" weight={600} truncate>
                            {step.artifact_name}
                        </Text>
                        <Chip tone={meta.tone}>{meta.label}</Chip>
                    </div>
                    <Text
                        as="p"
                        variant="caption"
                        tone="muted"
                        className="mt-1"
                    >
                        {regenerationActionLabel(step.action)}
                        {step.depends_on.length
                            ? ` · 等待 ${step.depends_on.length} 个前序产物`
                            : ""}
                    </Text>
                    {step.blockers.length ? (
                        <div className="mt-2 space-y-1">
                            {step.blockers.slice(0, 3).map((blocker) => (
                                <Text
                                    key={`${blocker.code}:${blocker.entity_id || ""}`}
                                    as="p"
                                    variant="caption"
                                    tone="warning"
                                >
                                    {blocker.message}
                                </Text>
                            ))}
                        </div>
                    ) : null}
                    <Link
                        href={versionsHref(
                            projectId,
                            step.artifact_id,
                            step.unit_id,
                        )}
                        className="mt-2 inline-flex text-caption text-[var(--s-muted)] transition-colors hover:text-[var(--s-ink)]"
                    >
                        查看版本
                    </Link>
                </div>
            </div>
        </Surface>
    );
}

function currentMissingDependencies(
    dependencies: AssetDependencyInput[],
    expectedVersionId: string | null,
): AssetDependencyInput[] {
    return dependencies.filter(
        (dependency) =>
            !dependency.asset_exists &&
            dependency.downstream_version_id === expectedVersionId,
    );
}

function AssetReplacementEditor({
    projectId,
    step,
}: {
    projectId: string;
    step: RegenerationPlanStep;
}) {
    const { message } = useApp();
    const dependencies = useArtifactAssetDependencies(step.artifact_id);
    const assets = useAssets(projectId, null);
    const setInput = useSetRegenerationPlanStepInput(projectId);
    const [replacements, setReplacements] = useState<
        Record<string, string>
    >(step.input.replacements || {});

    useEffect(() => {
        setReplacements(step.input.replacements || {});
    }, [step.id, step.input.replacements]);

    const missing = useMemo(
        () =>
            currentMissingDependencies(
                dependencies.data || [],
                step.expected_version_id,
            ),
        [dependencies.data, step.expected_version_id],
    );
    const ready =
        missing.length > 0 &&
        missing.every((dependency) =>
            Boolean(replacements[dependency.upstream_asset_id]),
        );

    const submit = async () => {
        if (!ready) return;
        try {
            await setInput.mutateAsync({
                stepId: step.id,
                replacements,
            });
            message.success("替代素材已写入计划");
        } catch (error) {
            message.error(
                error instanceof Error
                    ? error.message
                    : "替代素材保存失败",
            );
        }
    };

    if (dependencies.isLoading || assets.isLoading) {
        return (
            <div className="mt-3 flex items-center gap-2 py-3 text-caption text-[var(--s-faint)]">
                <Spin size="small" />
                读取缺失素材与候选项…
            </div>
        );
    }
    if (dependencies.isError || assets.isError) {
        return (
            <div className="mt-3 flex items-center justify-between gap-3">
                <Text variant="caption" tone="danger">
                    素材依赖读取失败
                </Text>
                <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                        void dependencies.refetch();
                        void assets.refetch();
                    }}
                >
                    重试
                </Button>
            </div>
        );
    }
    if (!missing.length) {
        return (
            <Text
                as="p"
                variant="caption"
                tone="warning"
                className="mt-3"
            >
                当前版本已找不到可替换的直接缺失素材，请重新创建计划。
            </Text>
        );
    }

    const selected = new Set(Object.values(replacements));
    return (
        <div className="mt-3 space-y-3 border-t border-[var(--hairline)] pt-3">
            {missing.map((dependency) => {
                const snapshot = dependency.upstream_asset || {};
                const current = replacements[dependency.upstream_asset_id];
                const options = (assets.data || [])
                    .filter(
                        (asset) =>
                            asset.id !== dependency.upstream_asset_id &&
                            compatibleReplacementAsset(snapshot, asset) &&
                            (!selected.has(asset.id) || asset.id === current),
                    )
                    .map((asset) => ({
                        value: asset.id,
                        label: `${asset.name || asset.id} · ${asset.kind}`,
                    }));
                return (
                    <div key={dependency.id}>
                        <Text
                            as="div"
                            variant="caption"
                            tone="muted"
                            className="mb-1.5"
                        >
                            {snapshot.name || dependency.upstream_asset_id}
                            {snapshot.kind ? ` · ${snapshot.kind}` : ""}
                        </Text>
                        <Select
                            className="w-full"
                            placeholder={
                                options.length
                                    ? "选择同作用域的兼容素材"
                                    : "没有兼容候选素材"
                            }
                            value={current}
                            options={options}
                            disabled={!options.length}
                            onChange={(assetId) =>
                                setReplacements((previous) => ({
                                    ...previous,
                                    [dependency.upstream_asset_id]: assetId,
                                }))
                            }
                        />
                    </div>
                );
            })}
            <Button
                size="sm"
                variant="primary"
                disabled={!ready}
                loading={
                    setInput.isPending &&
                    setInput.variables?.stepId === step.id
                }
                onClick={() => void submit()}
            >
                保存替代素材
            </Button>
        </div>
    );
}

function AttemptHistoryDisclosure({
    step,
}: {
    step: RegenerationPlanStep;
}) {
    if (!step.attempt_history.length) return null;
    return (
        <details className="mt-3 border-t border-[var(--hairline)] pt-3">
            <summary className="cursor-pointer text-caption font-medium text-[var(--s-muted)] transition-colors hover:text-[var(--s-ink)]">
                查看 {step.attempt_history.length} 次历史失败
            </summary>
            <div className="mt-2 space-y-2">
                {step.attempt_history.map((attempt) => (
                    <div
                        key={`${attempt.attempt}:${attempt.recorded_at}`}
                        className="rounded-[var(--r-sm)] bg-[var(--s-panel)] px-3 py-2"
                    >
                        <Text
                            as="p"
                            variant="caption"
                            tone="faint"
                        >
                            第 {attempt.attempt + 1} 次尝试
                            {attempt.job_id
                                ? ` · Job ${attempt.job_id.slice(0, 12)}`
                                : ""}
                        </Text>
                        {attempt.error ? (
                            <Text
                                as="p"
                                variant="caption"
                                tone="danger"
                                className="mt-1 leading-5"
                            >
                                {attempt.error}
                            </Text>
                        ) : null}
                    </div>
                ))}
            </div>
        </details>
    );
}

function PlanStepCard({
    projectId,
    step,
    index,
}: {
    projectId: string;
    step: RegenerationPlanStep;
    index: number;
}) {
    const meta = regenerationStepMeta(step.status);
    return (
        <Surface level="raised" radius="sm" hairline inset="3">
            <div className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--s-panel)] text-caption text-[var(--s-faint)]">
                    {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[var(--s-faint)]">
                            {statusIcon(step.status)}
                        </span>
                        <Text variant="body" tone="ink" weight={600} truncate>
                            {step.artifact_name}
                        </Text>
                        <Chip tone={meta.tone}>{meta.label}</Chip>
                    </div>
                    <Text
                        as="p"
                        variant="caption"
                        tone="muted"
                        className="mt-1"
                    >
                        {regenerationActionLabel(step.action)}
                        {` · 第 ${step.execution_attempt + 1} 次尝试`}
                        {step.depends_on_artifact_ids.length
                            ? ` · ${step.depends_on_artifact_ids.length} 个前序步骤`
                            : ""}
                    </Text>
                    {step.job_id ? (
                        <Text
                            as="p"
                            variant="mono"
                            tone="faint"
                            className="mt-1"
                        >
                            Job {step.job_id.slice(0, 12)}
                        </Text>
                    ) : null}
                    {step.error ? (
                        <Text
                            as="p"
                            variant="caption"
                            tone="danger"
                            className="mt-2 leading-5"
                        >
                            {step.error}
                        </Text>
                    ) : null}
                    {step.blockers.length ? (
                        <div className="mt-2 space-y-1">
                            {step.blockers.slice(0, 3).map((blocker) => (
                                <Text
                                    key={`${blocker.code}:${blocker.entity_id || ""}`}
                                    as="p"
                                    variant="caption"
                                    tone="warning"
                                >
                                    {blocker.message}
                                </Text>
                            ))}
                        </div>
                    ) : null}
                    {step.status === "requires_input" ? (
                        <AssetReplacementEditor
                            projectId={projectId}
                            step={step}
                        />
                    ) : null}
                    <AttemptHistoryDisclosure step={step} />
                    <Link
                        href={versionsHref(
                            projectId,
                            step.artifact_id,
                            step.unit_id,
                        )}
                        className="mt-2 inline-flex text-caption text-[var(--s-muted)] transition-colors hover:text-[var(--s-ink)]"
                    >
                        查看版本
                    </Link>
                </div>
            </div>
        </Surface>
    );
}

export function RegenerationPlanModal({
    projectId,
    root,
    existingPlanId = null,
    open,
    onClose,
}: {
    projectId: string;
    root: ProjectArtifactFreshnessItem | null;
    existingPlanId?: string | null;
    open: boolean;
    onClose: () => void;
}) {
    const { message } = useApp();
    const rootArtifactId = root?.artifact_id || null;
    const [planId, setPlanId] = useState<string | null>(
        existingPlanId,
    );
    const preview = usePreviewRegenerationCascade(projectId);
    const createPlan = useCreateRegenerationPlan(projectId);
    const planQuery = useRegenerationPlan(planId);
    const startPlan = useStartRegenerationPlan(projectId);
    const retryPlan = useRetryRegenerationPlan(projectId);
    const cancelPlan = useCancelRegenerationPlan(projectId);

    const previewCascade = preview.mutateAsync;
    const resetPreview = preview.reset;
    const resetCreate = createPlan.reset;

    useEffect(() => {
        if (!open) return;
        resetPreview();
        resetCreate();
        if (existingPlanId) {
            setPlanId(existingPlanId);
            return;
        }
        setPlanId(null);
        if (!rootArtifactId) return;
        void previewCascade({
            artifact_ids: [rootArtifactId],
            include_downstream: true,
        });
    }, [
        open,
        existingPlanId,
        rootArtifactId,
        previewCascade,
        resetPreview,
        resetCreate,
    ]);

    const plan = planQuery.data || createPlan.data || null;
    const terminal = plan
        ? isRegenerationPlanTerminal(plan.status)
        : false;
    const unresolvedInput = regenerationPlanHasUnresolvedInput(plan);
    const retryBlocker = regenerationPlanRetryBlocker(plan);
    const planMeta = plan ? regenerationPlanMeta(plan.status) : null;

    const create = async () => {
        if (!rootArtifactId) return;
        try {
            const created = await createPlan.mutateAsync({
                artifact_ids: [rootArtifactId],
                include_downstream: true,
            });
            setPlanId(created.id);
            message.success("级联修复计划已创建");
        } catch (error) {
            message.error(
                error instanceof Error ? error.message : "计划创建失败",
            );
        }
    };

    const start = async () => {
        if (!plan) return;
        try {
            const started = await startPlan.mutateAsync(plan.id);
            setPlanId(started.id);
            message.success(
                started.status === "succeeded"
                    ? "修复计划已完成"
                    : "修复计划已开始",
            );
        } catch (error) {
            message.error(
                error instanceof Error ? error.message : "计划启动失败",
            );
        }
    };

    const retry = async () => {
        if (!plan || plan.status !== "failed" || retryBlocker) return;
        try {
            const retried = await retryPlan.mutateAsync({
                planId: plan.id,
                expectedExecutionAttempt: plan.execution_attempt,
            });
            setPlanId(retried.id);
            message.success(
                retried.status === "succeeded"
                    ? "失败步骤重试后已完成"
                    : "失败步骤已进入新的执行尝试",
            );
        } catch (error) {
            message.error(
                error instanceof Error ? error.message : "计划重试失败",
            );
        }
    };

    const cancel = async () => {
        if (!plan) return;
        try {
            await cancelPlan.mutateAsync(plan.id);
            message.success("修复计划已取消");
        } catch (error) {
            message.error(
                error instanceof Error ? error.message : "计划取消失败",
            );
        }
    };

    const footer = [
        <Button key="close" variant="ghost" onClick={onClose}>
            {terminal ? "关闭" : "稍后处理"}
        </Button>,
    ];
    if (!plan && preview.data) {
        footer.push(
            <Button
                key="create"
                variant="primary"
                icon={<GitBranch className="size-3.5" />}
                loading={createPlan.isPending}
                onClick={() => void create()}
            >
                创建计划
            </Button>,
        );
    }
    if (plan && !terminal) {
        footer.push(
            <Button
                key="cancel"
                variant="danger"
                loading={cancelPlan.isPending}
                onClick={() => void cancel()}
            >
                取消计划
            </Button>,
        );
    }
    if (plan?.status === "draft") {
        footer.push(
            <Tooltip
                key="start-tip"
                title={
                    unresolvedInput
                        ? "先为所有缺失素材选择替代项"
                        : undefined
                }
            >
                <span>
                    <Button
                        variant="primary"
                        icon={<Play className="size-3.5" />}
                        disabled={unresolvedInput}
                        loading={startPlan.isPending}
                        onClick={() => void start()}
                    >
                        开始执行
                    </Button>
                </span>
            </Tooltip>,
        );
    }
    if (plan?.status === "failed") {
        footer.push(
            <Tooltip
                key="retry-tip"
                title={retryBlocker || undefined}
            >
                <span>
                    <Button
                        variant="primary"
                        icon={<RefreshCw className="size-3.5" />}
                        disabled={Boolean(retryBlocker)}
                        loading={retryPlan.isPending}
                        onClick={() => void retry()}
                    >
                        重试失败步骤
                    </Button>
                </span>
            </Tooltip>,
        );
    }

    return (
        <Modal
            title={
                <div>
                    <div className="flex items-center gap-2">
                        <GitBranch className="size-4 text-[var(--s-faint)]" />
                        <Text variant="body" tone="ink" weight={600}>
                            级联修复计划
                        </Text>
                        {planMeta ? (
                            <Chip tone={planMeta.tone}>{planMeta.label}</Chip>
                        ) : null}
                    </div>
                    <Text
                        as="p"
                        variant="caption"
                        tone="faint"
                        className="mt-1"
                    >
                        {existingPlanId
                            ? "查看或继续一个已经持久化的修复计划。"
                            : `从 ${root?.name || "当前内容"} 开始，按依赖顺序修复当前下游。`}
                    </Text>
                </div>
            }
            width={760}
            open={open}
            onCancel={onClose}
            footer={footer}
            styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
        >
            {preview.isPending && !plan ? (
                <div className="flex flex-col items-center gap-3 py-16">
                    <Spin size="large" />
                    <Text variant="caption" tone="faint">
                        正在计算当前依赖顺序…
                    </Text>
                </div>
            ) : preview.isError && !plan ? (
                <div className="flex flex-col items-center gap-3 py-12 text-center">
                    <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                    <Text variant="body" tone="ink">
                        级联修复预览失败
                    </Text>
                    <Text variant="caption" tone="muted">
                        {preview.error.message}
                    </Text>
                    <Button
                        size="sm"
                        icon={<RefreshCw className="size-3.5" />}
                        onClick={() => {
                            if (!rootArtifactId) return;
                            void preview.mutateAsync({
                                artifact_ids: [rootArtifactId],
                                include_downstream: true,
                            });
                        }}
                    >
                        重新计算
                    </Button>
                </div>
            ) : planQuery.isError ? (
                <div className="flex flex-col items-center gap-3 py-12 text-center">
                    <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                    <Text variant="body" tone="ink">
                        修复计划读取失败
                    </Text>
                    <Text variant="caption" tone="muted">
                        {planQuery.error.message}
                    </Text>
                    <Button
                        size="sm"
                        onClick={() => void planQuery.refetch()}
                    >
                        重试
                    </Button>
                </div>
            ) : plan ? (
                <div>
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                            {planMeta ? (
                                <StatusDot tone={planMeta.dotTone} />
                            ) : null}
                            <Text variant="body" tone="ink" weight={600}>
                                第 {plan.execution_attempt + 1} 次执行 · {plan.summary.completed || 0}/
                                {plan.summary.total || plan.steps?.length || 0} 步已完成
                            </Text>
                        </div>
                        {plan.status === "running" ? (
                            <Text variant="caption" tone="info">
                                页面关闭后计划仍会持久化执行
                            </Text>
                        ) : plan.status === "failed" ? (
                            <Text variant="caption" tone="warning">
                                重试只重置失败步骤，已成功版本会保留
                            </Text>
                        ) : null}
                    </div>
                    {plan.error ? (
                        <Surface
                            level="raised"
                            radius="sm"
                            hairline
                            inset="3"
                            className="mb-4"
                        >
                            <Text variant="caption" tone="danger">
                                {plan.error}
                            </Text>
                        </Surface>
                    ) : null}
                    <div className="space-y-2">
                        {(plan.steps || []).map((step, index) => (
                            <PlanStepCard
                                key={step.id}
                                projectId={projectId}
                                step={step}
                                index={index}
                            />
                        ))}
                    </div>
                </div>
            ) : preview.data ? (
                <div>
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                        <Text variant="body" tone="ink" weight={600}>
                            {preview.data.summary.total} 个产物 · {preview.data.summary.automatable} 步可自动执行
                        </Text>
                        <Text variant="caption" tone="faint">
                            创建前不会生成 Job 或修改版本
                        </Text>
                    </div>
                    <div className="space-y-2">
                        {preview.data.steps.map((step, index) => (
                            <PreviewStepCard
                                key={step.artifact_id}
                                projectId={projectId}
                                step={step}
                                index={index}
                            />
                        ))}
                    </div>
                </div>
            ) : null}
        </Modal>
    );
}
