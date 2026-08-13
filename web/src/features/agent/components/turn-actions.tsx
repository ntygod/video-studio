"use client";

import { useMemo } from "react";
import { Undo2 } from "lucide-react";

import { PolicyApprovalCard } from "@/features/agent/components/policy-approval-card";
import { RuntimeCostSummary } from "@/features/agent/components/runtime-cost-summary";
import { revertTurn, type AgentTurn } from "@/services/api";
import {
    useResolveRuntimePolicyDecision,
    useTurnPolicyDecisions,
} from "@/services/queries";
import { Button, Popconfirm, useApp } from "@/shared/ui";

/** 高风险动作确认、费用摘要与「撤销本回合」操作区。 */
export function TurnActions({
    turnId,
    entities,
    onReverted,
    onChanged,
}: {
    turnId: string | null;
    entities: AgentTurn["created_entities"];
    onReverted?: () => void;
    onChanged?: () => void;
}) {
    const { message } = useApp();
    const decisions = useTurnPolicyDecisions(turnId, Boolean(turnId));
    const resolveDecision = useResolveRuntimePolicyDecision(turnId);
    const pending = useMemo(
        () =>
            (decisions.data || []).filter(
                (decision) => decision.status === "pending",
            ),
        [decisions.data],
    );

    if (!turnId) return null;

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

    const revert = async () => {
        try {
            const result = await revertTurn(turnId);
            message.success(
                `已撤销 ${result.reverted.length} 项${
                    result.skipped.length
                        ? `，跳过 ${result.skipped.length} 项`
                        : ""
                }`,
            );
            onReverted?.();
            onChanged?.();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "撤销失败");
        }
    };

    return (
        <div className="px-3 pb-2">
            <RuntimeCostSummary turnId={turnId} />
            {pending.map((decision) => (
                <PolicyApprovalCard
                    key={decision.id}
                    decision={decision}
                    resolving={
                        resolveDecision.isPending &&
                        resolveDecision.variables?.decisionId === decision.id
                    }
                    onApprove={() => void resolve(decision.id, true)}
                    onDeny={() => void resolve(decision.id, false)}
                />
            ))}
            {entities.length ? (
                <div className="flex items-center justify-end">
                    <Popconfirm
                        title="撤销本回合？"
                        description="将删除本回合直接创建的稿件、单元与素材。"
                        okText="撤销"
                        cancelText="取消"
                        onConfirm={() => void revert()}
                    >
                        <Button
                            size="sm"
                            icon={<Undo2 className="size-3.5" />}
                        >
                            撤销本回合
                        </Button>
                    </Popconfirm>
                </div>
            ) : null}
        </div>
    );
}
