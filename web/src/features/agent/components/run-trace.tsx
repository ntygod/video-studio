"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, CircleCheck, CircleX, LoaderCircle } from "lucide-react";

import type { TurnStep } from "@/services/api";
import { cn } from "@/shared/lib/utils";
import { Divider } from "@/shared/ui/divider";
import { Progress } from "@/shared/ui/progress";
import { Surface } from "@/shared/ui/surface";
import { Text } from "@/shared/ui/text";

/**
 * Agent 运行轨迹（docs/ui-craft.md §4.2）。
 * 四列对齐：状态 / 工具名 / 摘要 / 耗时；失败行左侧 2px 竖条，不做红底。
 */
export function RunTrace({ steps, running }: { steps: TurnStep[]; running: boolean }) {
    const [collapsed, setCollapsed] = useState(false);

    if (!steps.length && !running) return null;

    return (
        <Surface level="canvas" radius="md" hairline className="mb-2 overflow-hidden">
            <button
                type="button"
                onClick={() => setCollapsed(!collapsed)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
                aria-expanded={!collapsed}
            >
                {collapsed ? (
                    <ChevronRight className="size-3.5 text-[var(--s-faint)]" />
                ) : (
                    <ChevronDown className="size-3.5 text-[var(--s-faint)]" />
                )}
                <Text variant="label" tone="ink">
                    运行轨迹
                </Text>
                <Text variant="mono" tone="muted">
                    {steps.length} 步
                </Text>
                {running ? (
                    <span className="ml-auto inline-flex items-center gap-1.5">
                        <LoaderCircle className="size-3 animate-spin text-[var(--s-muted)]" />
                        <Text variant="caption" tone="muted">
                            进行中
                        </Text>
                    </span>
                ) : null}
            </button>
            {!collapsed ? (
                <>
                    <Divider />
                    <div className="hide-scrollbar max-h-48 space-y-0.5 overflow-y-auto px-2 py-1.5">
                        {steps.map((step) => (
                            <div
                                key={step.id}
                                className={cn(
                                    "grid grid-cols-[16px_auto_1fr_auto] items-center gap-2 rounded px-2 py-1",
                                    step.status === "failed" && "relative",
                                )}
                            >
                                {step.status === "failed" ? (
                                    <span
                                        aria-hidden
                                        className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-danger)]"
                                    />
                                ) : null}
                                {step.status === "ok" ? (
                                    <CircleCheck className="size-3.5 shrink-0 text-[var(--s-success)]" />
                                ) : step.status === "failed" ? (
                                    <CircleX className="size-3.5 shrink-0 text-[var(--s-danger)]" />
                                ) : (
                                    <LoaderCircle className="size-3.5 shrink-0 animate-spin text-[var(--s-muted)]" />
                                )}
                                <Text variant="mono" tone="ink" className="shrink-0">
                                    {step.tool_name || "error"}
                                </Text>
                                <Text
                                    variant="caption"
                                    tone={step.status === "failed" ? "danger" : "muted"}
                                    truncate
                                    className="min-w-0 flex-1"
                                >
                                    {step.summary || step.error}
                                </Text>
                                <Text variant="mono" tone="faint" className="shrink-0">
                                    {step.duration_ms ? `${step.duration_ms}ms` : ""}
                                </Text>
                            </div>
                        ))}
                        {running ? (
                            <div className="px-2 py-1">
                                <Progress indeterminate />
                            </div>
                        ) : null}
                    </div>
                </>
            ) : null}
        </Surface>
    );
}
