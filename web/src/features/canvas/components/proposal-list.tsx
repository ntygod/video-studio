"use client";

import { Check, GitPullRequestArrow, X } from "lucide-react";

import { artifactKindLabel } from "@/features/workspace/lib/labels";
import type { Proposal, ProposalOperation } from "@/services/api";
import { useAcceptProposal, useRejectProposal } from "@/services/queries";
import { Button, Surface, Tag, Text, useApp } from "@/shared/ui";

/**
 * 单条 operation 的简短标签。
 * <p>
 * 稿件提案是 JSON Patch（有 path），结构提案是 {action, unit_id}（没有 path），
 * 两者要分别取值，否则结构提案会渲染成一串 undefined。
 */
function operationLabel(operation: ProposalOperation): string {
    if (operation.path) return operation.path;
    const structure = operation as unknown as { action?: string; unit_id?: string };
    return structure.action ? `${structure.action} ${structure.unit_id || ""}`.trim() : "变更";
}

/**
 * 待处理的 AI 变更提案。
 * <p>
 * AI 不能直接覆盖已有内容，只能提案；用户采纳后才会生成新的 artifact 版本
 * 或落地结构变更。逐条勾选采纳在对话内的 ProposalCard 里。
 */
export function ProposalList({ projectId, proposals }: { projectId: string; proposals: Proposal[] }) {
    const { message } = useApp();
    const acceptProposal = useAcceptProposal(projectId);
    const rejectProposal = useRejectProposal(projectId);

    if (!proposals.length) return null;

    const decide = async (proposal: Proposal, decision: "accept" | "reject") => {
        try {
            if (decision === "accept") await acceptProposal.mutateAsync(proposal.id);
            else await rejectProposal.mutateAsync(proposal.id);
            message.success(decision === "accept" ? "已采用建议并保存新版本" : "已暂不采用这条建议");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        }
    };

    const busyId = acceptProposal.isPending
        ? acceptProposal.variables
        : rejectProposal.isPending
          ? rejectProposal.variables
          : null;

    return (
        <Surface as="section" level="panel" radius="md" lift hairlineStrong className="p-4">
            <Text as="h2" variant="body" tone="ink" weight={600} className="flex items-center gap-2">
                <GitPullRequestArrow className="size-4" />
                AI 修改建议
                <span className="text-caption font-normal text-[var(--s-muted)]">{proposals.length} 条待处理</span>
            </Text>

            <div className="mt-3 space-y-2">
                {proposals.map((proposal) => (
                    <article
                        key={proposal.id}
                        className="rounded-[var(--r-sm)] border border-[var(--hairline)] bg-[var(--s-raised)] p-3"
                    >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                                <Text as="h3" variant="body" tone="ink" weight={500}>
                                    {proposal.title}
                                </Text>
                                <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                                    {proposal.rationale || "AI 建议调整当前内容"}
                                </Text>
                                {proposal.operations.length ? (
                                    <p className="mt-1.5 text-caption text-[var(--s-faint)]">
                                        影响 {proposal.operations.length} 处：
                                        {proposal.operations
                                            .slice(0, 3)
                                            .map(operationLabel)
                                            .join("、")}
                                        {proposal.operations.length > 3 ? " …" : ""}
                                    </p>
                                ) : null}
                            </div>
                            <Tag className="m-0 shrink-0">{artifactKindLabel(proposal.artifact_kind)}</Tag>
                        </div>

                        <div className="mt-3 flex gap-2">
                            <Button
                                size="sm"
                                variant="primary"
                                icon={<Check className="size-3.5" />}
                                loading={busyId === proposal.id && acceptProposal.isPending}
                                onClick={() => void decide(proposal, "accept")}
                            >
                                采用建议
                            </Button>
                            <Button
                                size="sm"
                                icon={<X className="size-3.5" />}
                                loading={busyId === proposal.id && rejectProposal.isPending}
                                onClick={() => void decide(proposal, "reject")}
                            >
                                暂不采用
                            </Button>
                        </div>
                    </article>
                ))}
            </div>
        </Surface>
    );
}
