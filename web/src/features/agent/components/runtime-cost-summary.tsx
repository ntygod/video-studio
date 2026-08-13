"use client";

import { CircleDollarSign, TriangleAlert } from "lucide-react";

import {
    useTurnRuntimeBudget,
    useTurnRuntimeCosts,
} from "@/services/queries";
import { Chip, Surface, Text } from "@/shared/ui";

function formatUsd(value: number): string {
    if (value === 0) return "$0";
    if (value < 0.01) return `$${value.toFixed(6)}`;
    return `$${value.toFixed(4)}`;
}

export function RuntimeCostSummary({
    turnId,
}: {
    turnId: string;
}) {
    const budget = useTurnRuntimeBudget(turnId);
    const state = budget.data;
    const runtimeActive = Boolean(
        state && ["queued", "running"].includes(state.plan_status),
    );
    const costs = useTurnRuntimeCosts(turnId, runtimeActive);
    if (!state && !budget.isError) return null;
    if (budget.isError) {
        return (
            <Surface level="raised" radius="sm" hairline inset="2" className="mb-3">
                <Text variant="caption" tone="danger">
                    本回合费用读取失败
                </Text>
            </Surface>
        );
    }
    if (!state) return null;

    const usage = state.usage;
    const entries = costs.data || [];
    return (
        <Surface level="raised" radius="sm" hairline inset="2" className="mb-3">
            <div className="flex flex-wrap items-center gap-2">
                <CircleDollarSign className="size-4 text-[var(--s-faint)]" />
                <Text variant="label" tone="ink" weight={600}>
                    本回合 {formatUsd(usage.cost_usd || 0)}
                </Text>
                <Chip tone="default">
                    {usage.total_tokens || 0} tokens
                </Chip>
                <Chip tone="default">
                    {usage.provider_calls || 0} 次模型调用
                </Chip>
                {state.budget.max_cost_usd !== undefined ? (
                    <Text variant="caption" tone="faint">
                        上限 {formatUsd(state.budget.max_cost_usd)}
                    </Text>
                ) : null}
            </div>
            {state.violation ? (
                <div className="mt-2 flex items-center gap-1.5 text-caption text-[var(--s-danger)]">
                    <TriangleAlert className="size-3.5" />
                    已达到预算限制：{state.violation.actual}/{state.violation.limit}
                </div>
            ) : null}
            {usage.unpriced_calls ? (
                <div className="mt-2 flex items-center gap-1.5 text-caption text-[var(--s-warning)]">
                    <TriangleAlert className="size-3.5" />
                    {usage.unpriced_calls} 次调用缺少模型价格，当前合计不含这些费用
                </div>
            ) : null}
            {entries.length ? (
                <details className="mt-2">
                    <summary className="cursor-pointer text-caption text-[var(--s-muted)]">
                        查看费用明细
                    </summary>
                    <div className="mt-2 space-y-1.5">
                        {entries.slice(0, 5).map((entry) => (
                            <div
                                key={entry.id}
                                className="flex items-center justify-between gap-3 text-caption"
                            >
                                <span className="min-w-0 truncate text-[var(--s-muted)]">
                                    {entry.provider_name || "Provider"} · {entry.model_id || "未知模型"}
                                </span>
                                <span className="shrink-0 font-mono text-[var(--s-faint)]">
                                    {entry.priced
                                        ? formatUsd(entry.amount_usd)
                                        : "未定价"}
                                </span>
                            </div>
                        ))}
                    </div>
                </details>
            ) : null}
        </Surface>
    );
}
