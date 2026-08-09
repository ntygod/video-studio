"use client";

import { App, Button, Tag } from "antd";
import { Check, GitPullRequestArrow, X } from "lucide-react";

import { artifactKindLabel } from "@/features/workspace/lib/labels";
import type { Proposal } from "@/services/api";
import { useAcceptProposal, useRejectProposal } from "@/services/queries";

/**
 * 待处理的 AI 变更提案。
 * <p>
 * AI 不能直接改项目，只能提案；用户采纳后才会生成新的 artifact 版本。
 * P1 会把它移进对话流里并支持逐条勾选操作，这里先保持整份采纳/拒绝。
 */
export function ProposalList({ projectId, proposals }: { projectId: string; proposals: Proposal[] }) {
    const { message } = App.useApp();
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
        <section className="rounded-lg border border-[var(--studio-action-line)] bg-[var(--studio-action-soft)] p-4">
            <h2 className="flex items-center gap-2 text-[13px] font-semibold text-[var(--studio-ink)]">
                <GitPullRequestArrow className="size-4" />
                AI 修改建议
                <span className="text-[11px] font-normal text-[var(--studio-muted)]">{proposals.length} 条待处理</span>
            </h2>

            <div className="mt-3 space-y-2">
                {proposals.map((proposal) => (
                    <article
                        key={proposal.id}
                        className="rounded-md border border-[var(--studio-line)] bg-[var(--studio-surface)] p-3"
                    >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                                <h3 className="text-[13px] font-medium text-[var(--studio-ink)]">{proposal.title}</h3>
                                <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                                    {proposal.rationale || "AI 建议调整当前内容"}
                                </p>
                                {proposal.operations.length ? (
                                    <p className="mt-1.5 text-[10px] text-[var(--studio-faint)]">
                                        影响 {proposal.operations.length} 处：
                                        {proposal.operations.slice(0, 3).map((op) => op.path).join("、")}
                                        {proposal.operations.length > 3 ? " …" : ""}
                                    </p>
                                ) : null}
                            </div>
                            <Tag className="m-0 shrink-0">{artifactKindLabel(proposal.artifact_kind)}</Tag>
                        </div>

                        <div className="mt-3 flex gap-2">
                            <Button
                                size="small"
                                type="primary"
                                icon={<Check className="size-3.5" />}
                                loading={busyId === proposal.id && acceptProposal.isPending}
                                onClick={() => void decide(proposal, "accept")}
                            >
                                采用建议
                            </Button>
                            <Button
                                size="small"
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
        </section>
    );
}
