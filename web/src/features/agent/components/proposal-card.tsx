"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FileDiff } from "lucide-react";

import {
    acceptProposal,
    previewProposal,
    rejectProposal,
    type Proposal,
    type ProposalPreview,
} from "@/services/api";
import { cn } from "@/shared/lib/utils";
import { Button, Checkbox, Popconfirm, Surface, Text, useApp } from "@/shared/ui";

/**
 * 内联提案卡：字段级 before→after + 逐条勾选采纳。
 * 视觉规格见 docs/ui-redesign.md §4.2(c)。
 */
export function ProposalCard({
    proposal,
    onSettled,
    onChanged,
}: {
    proposal: Proposal;
    onSettled?: () => void;
    onChanged?: () => void;
}) {
    const { message } = useApp();
    const [preview, setPreview] = useState<ProposalPreview | null>(null);
    const [checked, setChecked] = useState<boolean[]>(() => proposal.operations.map(() => true));
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        let alive = true;
        previewProposal(proposal.id)
            .then((data) => {
                if (alive) setPreview(data);
            })
            .catch(() => {});
        return () => {
            alive = false;
        };
    }, [proposal.id]);

    // 结构提案改的是单元树，operations 是 {action, unit_id} 而不是 JSON Patch，
    // 得用预览返回的可读摘要渲染，不能套字段级 diff。
    const isStructure = proposal.artifact_kind === "structure";
    const structureChanges = preview?.changes || [];

    const isApplicable = (index: number) => {
        if (!isStructure) return true;
        const change = structureChanges.find((item) => item.index === index);
        // 预览还没回来时先按可用处理，避免按钮闪一下禁用。
        return change ? change.applicable : true;
    };

    // 不可应用的条目即使勾着也不能提交，否则后端会整份报错。
    const selectedIndices = proposal.operations
        .map((_, index) => index)
        .filter((index) => checked[index] && isApplicable(index));

    const diffFor = (path: string) =>
        (preview?.field_diffs || []).find((diff) => diff.path === path);

    const renderRow = (index: number, label: string, detail: ReactNode, disabled = false) => (
        <div
            key={`${index}-${label}`}
            className={cn(
                "flex items-start gap-2 rounded-[var(--r-sm)] bg-[var(--s-raised)] px-2 py-1.5",
                disabled ? "opacity-60" : "cursor-pointer",
            )}
        >
            <Checkbox
                checked={checked[index]}
                disabled={disabled}
                label={`选择修改 ${label}`}
                onChange={(next) =>
                    setChecked((current) =>
                        current.map((value, itemIndex) =>
                            itemIndex === index ? next : value,
                        ),
                    )
                }
            />
            <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-caption text-[var(--s-faint)]">{label}</span>
                <span className="mt-0.5 block text-caption leading-4 text-[var(--s-muted)]">{detail}</span>
            </span>
        </div>
    );

    const accept = async () => {
        if (!selectedIndices.length) {
            message.warning("至少勾选一条修改");
            return;
        }
        setBusy(true);
        try {
            await acceptProposal(proposal.id, selectedIndices);
            message.success("提案已采纳");
            onSettled?.();
            onChanged?.();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "采纳失败");
        } finally {
            setBusy(false);
        }
    };

    const reject = async () => {
        setBusy(true);
        try {
            await rejectProposal(proposal.id);
            message.info("提案已拒绝");
            onSettled?.();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "拒绝失败");
        } finally {
            setBusy(false);
        }
    };

    if (proposal.status !== "pending") return null;

    return (
        <Surface
            level="panel"
            radius="md"
            lift
            className="my-2 border border-[var(--s-action-line)] bg-[var(--s-action-soft)] p-2.5"
        >
            <div className="flex items-center gap-1.5">
                <FileDiff className="size-3.5 text-[var(--s-faint)]" />
                <Text variant="label" tone="ink" weight={500} truncate className="min-w-0 flex-1">
                    {proposal.title}
                </Text>
            </div>
            {proposal.rationale ? (
                <p className="mt-1 text-caption leading-4 text-[var(--s-muted)]">{proposal.rationale}</p>
            ) : null}

            <div className="mt-2 space-y-1">
                {isStructure
                    ? proposal.operations.map((operation, index) => {
                          const change = structureChanges.find((item) => item.index === index);
                          const inapplicable = change ? !change.applicable : false;
                          const unitLabel =
                              change?.title || String((operation as Record<string, unknown>).unit_id || "");
                          return renderRow(
                              index,
                              unitLabel,
                              <>
                                  {change?.summary || String((operation as Record<string, unknown>).action || "")}
                                  {inapplicable ? (
                                      <span className="ml-1 text-[var(--s-danger)]">
                                          （无法应用{change?.reason ? `：${change.reason}` : ""}）
                                      </span>
                                  ) : null}
                              </>,
                              inapplicable,
                          );
                      })
                    : proposal.operations.map((operation, index) => {
                          const diff = diffFor(operation.path);
                          return renderRow(
                              index,
                              operation.path,
                              <>
                                  {diff && diff.before !== undefined ? (
                                      <>
                                          <span className="line-through opacity-70">
                                              {typeof diff.before === "string"
                                                  ? diff.before
                                                  : JSON.stringify(diff.before)}
                                          </span>
                                          <span className="mx-1 text-[var(--s-faint)]">→</span>
                                      </>
                                  ) : null}
                                  {typeof operation.value === "string"
                                      ? operation.value
                                      : JSON.stringify(operation.value ?? "")}
                              </>,
                          );
                      })}
            </div>

            <div className="mt-2 flex items-center justify-end gap-1.5">
                <Button size="sm" variant="ghost" onClick={() => void reject()} disabled={busy}>
                    拒绝
                </Button>
                <Popconfirm
                    title="采纳选中的修改？"
                    okText="采纳"
                    cancelText="取消"
                    onConfirm={() => void accept()}
                >
                    <Button size="sm" variant="primary" loading={busy} disabled={!selectedIndices.length}>
                        采纳{selectedIndices.length ? `（${selectedIndices.length}）` : ""}
                    </Button>
                </Popconfirm>
            </div>
        </Surface>
    );
}
