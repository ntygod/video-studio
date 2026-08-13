"use client";

import { useState } from "react";
import Link from "next/link";
import {
    AlertTriangle,
    CircleDollarSign,
    RefreshCw,
    ShieldCheck,
} from "lucide-react";

import {
    runtimeCostPolicyMeta,
    type UnpricedProviderMode,
} from "@/services/api";
import {
    useProjectRuntimeCostPolicy,
    useUpdateProjectRuntimeCostPolicy,
} from "@/services/queries";
import {
    Button,
    Chip,
    Drawer,
    Spin,
    Surface,
    Text,
    Tooltip,
    useApp,
} from "@/shared/ui";

const MODES: UnpricedProviderMode[] = ["allow", "block"];

export function CostGovernanceCenter({
    projectId,
}: {
    projectId: string;
}) {
    const { message } = useApp();
    const [open, setOpen] = useState(false);
    const query = useProjectRuntimeCostPolicy(projectId);
    const update = useUpdateProjectRuntimeCostPolicy(projectId);
    const mode = query.data?.policy.unpriced_provider_mode || "allow";
    const meta = runtimeCostPolicyMeta(mode);

    const selectMode = async (next: UnpricedProviderMode) => {
        if (!query.data || next === mode) return;
        try {
            await update.mutateAsync({
                expectedRevision: query.data.revision,
                mode: next,
            });
            message.success(
                next === "block"
                    ? "已启用严格 Provider 计价"
                    : "已切换为尽力计价",
            );
        } catch (error) {
            message.error(
                error instanceof Error
                    ? error.message
                    : "成本治理策略保存失败",
            );
            void query.refetch();
        }
    };

    return (
        <>
            <Tooltip
                title={
                    query.isError
                        ? "Provider 成本策略读取失败"
                        : `${meta.label}：${meta.warning}`
                }
            >
                <Button
                    size="sm"
                    variant="ghost"
                    aria-label="打开 Provider 成本治理"
                    icon={<CircleDollarSign className="size-4" />}
                    onClick={() => setOpen(true)}
                >
                    <span className="hidden 2xl:inline">成本策略</span>
                    <span className="inline-flex min-w-8 items-center justify-center rounded-full bg-[var(--s-raised)] px-1 text-caption text-[var(--s-ink)]">
                        {query.isError ? "!" : meta.shortLabel}
                    </span>
                </Button>
            </Tooltip>

            <Drawer
                title={
                    <div>
                        <div className="flex items-center gap-2">
                            <Text
                                as="span"
                                variant="body"
                                tone="ink"
                                weight={600}
                            >
                                Provider 成本治理
                            </Text>
                            <Chip tone={mode === "block" ? "success" : "warning"}>
                                {meta.label}
                            </Chip>
                        </div>
                        <Text
                            as="p"
                            variant="caption"
                            tone="faint"
                            className="mt-0.5"
                        >
                            策略只影响新创建的 Agent 回合；运行中的回合继续使用已冻结快照。
                        </Text>
                    </div>
                }
                placement="right"
                size={480}
                open={open}
                onClose={() => setOpen(false)}
            >
                {query.isLoading && !query.data ? (
                    <div className="flex justify-center py-16">
                        <Spin size="large" />
                    </div>
                ) : query.isError ? (
                    <div className="flex flex-col items-center gap-3 py-12 text-center">
                        <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                        <Text variant="body" tone="ink">
                            Provider 成本策略读取失败
                        </Text>
                        <Button
                            size="sm"
                            icon={<RefreshCw className="size-3.5" />}
                            onClick={() => void query.refetch()}
                        >
                            重新读取
                        </Button>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {MODES.map((candidate) => {
                            const candidateMeta = runtimeCostPolicyMeta(candidate);
                            const selected = candidate === mode;
                            return (
                                <Surface
                                    key={candidate}
                                    level="raised"
                                    radius="sm"
                                    hairline
                                    inset="3"
                                >
                                    <div className="flex items-start gap-3">
                                        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-panel)] text-[var(--s-muted)]">
                                            {candidate === "block" ? (
                                                <ShieldCheck className="size-4" />
                                            ) : (
                                                <CircleDollarSign className="size-4" />
                                            )}
                                        </span>
                                        <div className="min-w-0 flex-1">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <Text
                                                    variant="body"
                                                    tone="ink"
                                                    weight={600}
                                                >
                                                    {candidateMeta.label}
                                                </Text>
                                                {selected ? (
                                                    <Chip tone="success">当前</Chip>
                                                ) : null}
                                            </div>
                                            <Text
                                                as="p"
                                                variant="caption"
                                                tone="muted"
                                                className="mt-1 leading-5"
                                            >
                                                {candidateMeta.description}
                                            </Text>
                                            <Text
                                                as="p"
                                                variant="caption"
                                                tone={
                                                    candidate === "block"
                                                        ? "info"
                                                        : "warning"
                                                }
                                                className="mt-1 leading-5"
                                            >
                                                {candidateMeta.warning}
                                            </Text>
                                            <Button
                                                size="sm"
                                                variant={
                                                    selected
                                                        ? "ghost"
                                                        : "secondary"
                                                }
                                                disabled={selected}
                                                loading={
                                                    update.isPending &&
                                                    update.variables?.mode ===
                                                        candidate
                                                }
                                                className="mt-3"
                                                onClick={() =>
                                                    void selectMode(candidate)
                                                }
                                            >
                                                {selected ? "已启用" : "启用此策略"}
                                            </Button>
                                        </div>
                                    </div>
                                </Surface>
                            );
                        })}

                        <Surface
                            level="raised"
                            radius="sm"
                            hairline
                            inset="3"
                        >
                            <Text variant="caption" tone="muted">
                                严格模式依赖模型价格配置。免费或自托管模型也应显式填写 0 价格，才能证明它是已计价而不是漏计。
                            </Text>
                            <Link
                                href="/settings"
                                className="mt-2 inline-flex text-caption text-[var(--s-muted)] transition-colors hover:text-[var(--s-ink)]"
                            >
                                打开模型设置
                            </Link>
                        </Surface>
                    </div>
                )}
            </Drawer>
        </>
    );
}
