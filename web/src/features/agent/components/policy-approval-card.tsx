"use client";

import { AlertTriangle, Check, ShieldAlert, X } from "lucide-react";

import type { RuntimePolicyDecision } from "@/services/api";
import { Button, Chip, Surface, Text } from "@/shared/ui";

function actionLabel(action: string): string {
    const labels: Record<string, string> = {
        generate_media: "派发媒体生成任务",
        write_artifact: "写入新稿件",
        create_units: "创建创作单元",
        propose_change: "创建修改提案",
        propose_restructure: "创建结构提案",
    };
    return labels[action] || action;
}

export function PolicyApprovalCard({
    decision,
    resolving,
    onApprove,
    onDeny,
}: {
    decision: RuntimePolicyDecision;
    resolving: boolean;
    onApprove: () => void;
    onDeny: () => void;
}) {
    const argumentsValue = decision.context.arguments || {};
    const preview = JSON.stringify(argumentsValue, null, 2);
    return (
        <Surface
            level="raised"
            radius="md"
            hairline
            inset="3"
            className="mb-3"
        >
            <div className="flex items-start gap-3">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-[var(--s-warning)]">
                    <ShieldAlert className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Text variant="body" tone="ink" weight={600}>
                            需要你的确认
                        </Text>
                        <Chip tone="warning">高风险</Chip>
                    </div>
                    <Text
                        as="p"
                        variant="caption"
                        tone="muted"
                        className="mt-1 leading-5"
                    >
                        AI 准备执行：{actionLabel(decision.action_type)}。该动作可能产生外部任务、成本或不可忽略的项目变更。
                    </Text>
                    {preview !== "{}" ? (
                        <pre className="mt-2 max-h-32 overflow-auto rounded-[var(--r-sm)] bg-[var(--s-panel)] p-2 text-[11px] leading-4 text-[var(--s-muted)]">
                            {preview}
                        </pre>
                    ) : null}
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Button
                            size="sm"
                            variant="primary"
                            icon={<Check className="size-3.5" />}
                            loading={resolving}
                            onClick={onApprove}
                        >
                            批准并继续
                        </Button>
                        <Button
                            size="sm"
                            variant="secondary"
                            icon={<X className="size-3.5" />}
                            disabled={resolving}
                            onClick={onDeny}
                        >
                            拒绝
                        </Button>
                        <span className="inline-flex items-center gap-1 text-caption text-[var(--s-faint)]">
                            <AlertTriangle className="size-3" />
                            决定会写入运行时审计记录
                        </span>
                    </div>
                </div>
            </div>
        </Surface>
    );
}
