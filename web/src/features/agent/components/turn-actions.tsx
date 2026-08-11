"use client";

import { Undo2 } from "lucide-react";

import { revertTurn, type AgentTurn } from "@/services/api";
import { Button, Popconfirm, useApp } from "@/shared/ui";

/** 「撤销本回合」：删除本回合直接创建的实体，跳过被用户改过的。 */
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

    if (!turnId || !entities.length) return null;

    const revert = async () => {
        try {
            const result = await revertTurn(turnId);
            message.success(`已撤销 ${result.reverted.length} 项${result.skipped.length ? `，跳过 ${result.skipped.length} 项` : ""}`);
            onReverted?.();
            onChanged?.();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "撤销失败");
        }
    };

    return (
        <div className="flex items-center justify-end px-3 pb-2">
            <Popconfirm
                title="撤销本回合？"
                description="将删除本回合直接创建的稿件、单元与素材。"
                okText="撤销"
                cancelText="取消"
                onConfirm={() => void revert()}
            >
                <Button size="sm" icon={<Undo2 className="size-3.5" />}>
                    撤销本回合
                </Button>
            </Popconfirm>
        </div>
    );
}
