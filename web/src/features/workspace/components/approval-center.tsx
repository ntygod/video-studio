"use client";

import { useState } from "react";
import { AlertTriangle, RefreshCw, ShieldAlert } from "lucide-react";

import { PolicyApprovalCard } from "@/features/agent/components/policy-approval-card";
import {
    useProjectPolicyDecisions,
    useResolveRuntimePolicyDecision,
} from "@/services/queries";
import {
    Button,
    Drawer,
    Spin,
    Text,
    Tooltip,
    useApp,
} from "@/shared/ui";

export function ApprovalCenter({ projectId }: { projectId: string }) {
    const { message } = useApp();
    const [open, setOpen] = useState(false);
    const decisions = useProjectPolicyDecisions(projectId);
    const resolveDecision = useResolveRuntimePolicyDecision(
        null,
        projectId,
    );
    const pending = decisions.data || [];
    const count = pending.length;

    const resolve = async (decisionId: string, approved: boolean) => {
        try {
            await resolveDecision.mutateAsync({ decisionId, approved });
            message.success(
                approved ? "已批准，AI 将继续执行" : "已拒绝该动作",
            );
        } catch (error) {
            message.error(
                error instanceof Error ? error.message : "确认操作失败",
            );
        }
    };

    if (!count && !decisions.isError && !open) return null;

    return (
        <>
            <Tooltip
                title={
                    decisions.isError
                        ? "待审批动作读取失败"
                        : `${count} 个 AI 动作等待确认`
                }
            >
                <Button
                    size="sm"
                    variant="ghost"
                    aria-label="打开 AI 待审批中心"
                    icon={<ShieldAlert className="size-4" />}
                    onClick={() => setOpen(true)}
                >
                    <span className="hidden 2xl:inline">待审批</span>
                    <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--s-raised)] px-1 text-caption text-[var(--s-ink)]">
                        {decisions.isError ? "!" : count}
                    </span>
                </Button>
            </Tooltip>

            <Drawer
                title={
                    <div>
                        <Text
                            as="span"
                            variant="body"
                            tone="ink"
                            weight={600}
                        >
                            AI 动作审批
                        </Text>
                        <Text
                            as="p"
                            variant="caption"
                            tone="faint"
                            className="mt-0.5"
                        >
                            高风险动作在获得确认前不会创建外部任务或写入项目。
                        </Text>
                    </div>
                }
                placement="right"
                size={480}
                open={open}
                onClose={() => setOpen(false)}
            >
                {decisions.isLoading && !decisions.data ? (
                    <div className="flex justify-center py-16">
                        <Spin size="large" />
                    </div>
                ) : decisions.isError ? (
                    <div className="flex flex-col items-center gap-3 py-12 text-center">
                        <AlertTriangle className="size-6 text-[var(--s-danger)]" />
                        <Text variant="body" tone="ink">
                            待审批动作读取失败
                        </Text>
                        <Button
                            size="sm"
                            icon={<RefreshCw className="size-3.5" />}
                            onClick={() => void decisions.refetch()}
                        >
                            重新读取
                        </Button>
                    </div>
                ) : pending.length ? (
                    <div>
                        {pending.map((decision) => (
                            <PolicyApprovalCard
                                key={decision.id}
                                decision={decision}
                                resolving={
                                    resolveDecision.isPending &&
                                    resolveDecision.variables?.decisionId ===
                                        decision.id
                                }
                                onApprove={() =>
                                    void resolve(decision.id, true)
                                }
                                onDeny={() =>
                                    void resolve(decision.id, false)
                                }
                            />
                        ))}
                    </div>
                ) : (
                    <div className="py-12 text-center">
                        <Text variant="body" tone="ink">
                            当前没有等待确认的动作
                        </Text>
                    </div>
                )}
            </Drawer>
        </>
    );
}
