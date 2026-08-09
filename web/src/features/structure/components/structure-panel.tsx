"use client";

import { useCallback, useMemo, useState } from "react";
import { App, Button, Input, Tooltip } from "antd";
import { ArrowLeft, BookMarked, FolderPlus, Search } from "lucide-react";
import Link from "next/link";

import { UnitCreateModal } from "@/features/structure/components/unit-create-modal";
import { UnitTree } from "@/features/structure/components/unit-tree";
import { useWorkspaceData, type UnitNode } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { META_ARTIFACT_KINDS } from "@/features/workspace/lib/labels";
import { useAssets, useDeleteUnit } from "@/services/queries";
import { ProgressRing, type CompletionTriple } from "@/shared/ui/indicators";

/** 一个单元被视为"完成"需要三段全绿。 */
function isComplete(triple: CompletionTriple): boolean {
    return triple[0] && triple[1] && triple[2];
}

/** 过滤单元树，保留命中节点及其祖先链。 */
function filterTree(nodes: UnitNode[], keep: (node: UnitNode) => boolean): UnitNode[] {
    return nodes
        .map((node) => {
            const children = filterTree(node.children, keep);
            if (!keep(node) && children.length === 0) return null;
            return { ...node, children };
        })
        .filter((node): node is UnitNode => node !== null);
}

/**
 * 左侧结构导航。
 * <p>
 * 长篇创作的主要定位入口：单元树 + 三段完成度 + 待处理建议数 + 搜索。
 */
export function StructurePanel() {
    const { message } = App.useApp();
    const { projectId, selectedUnitId, setSelectedUnit, hrefFor } = useWorkspaceRoute();
    const { project, unitTree, unitOptions } = useWorkspaceData();

    // 完成度需要项目全域的素材，与画布里按单元过滤的那份是不同的 query key。
    const allAssets = useAssets(projectId, null);
    const deleteUnit = useDeleteUnit(projectId);

    const [keyword, setKeyword] = useState("");
    const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
    const [createOpen, setCreateOpen] = useState(false);

    const artifactUnitIds = useMemo(() => {
        const ids = new Set<string>();
        (project?.artifacts || []).forEach((artifact) => {
            if (artifact.unit_id && !META_ARTIFACT_KINDS.includes(artifact.kind)) ids.add(artifact.unit_id);
        });
        return ids;
    }, [project?.artifacts]);

    const assetUnitIds = useMemo(() => {
        const media = new Set<string>();
        const renders = new Set<string>();
        (allAssets.data || []).forEach((asset) => {
            if (!asset.unit_id) return;
            if (asset.kind === "render") renders.add(asset.unit_id);
            else media.add(asset.unit_id);
        });
        return { media, renders };
    }, [allAssets.data]);

    const proposalCounts = useMemo(() => {
        const counts = new Map<string, number>();
        (project?.pending_proposals || []).forEach((proposal) => {
            if (!proposal.unit_id) return;
            counts.set(proposal.unit_id, (counts.get(proposal.unit_id) || 0) + 1);
        });
        return counts;
    }, [project?.pending_proposals]);

    const completionOf = useCallback(
        (unitId: string): CompletionTriple => [
            artifactUnitIds.has(unitId),
            assetUnitIds.media.has(unitId),
            assetUnitIds.renders.has(unitId),
        ],
        [artifactUnitIds, assetUnitIds],
    );

    const proposalCountOf = useCallback((unitId: string) => proposalCounts.get(unitId) || 0, [proposalCounts]);

    const visibleTree = useMemo(() => {
        const query = keyword.trim().toLowerCase();
        if (!query) return unitTree;
        return filterTree(unitTree, (node) =>
            node.title.toLowerCase().includes(query) || node.unit_type.toLowerCase().includes(query),
        );
    }, [keyword, unitTree]);

    const progress = useMemo(() => {
        const units = project?.units || [];
        if (!units.length) return { ratio: 0, done: 0, total: 0 };
        const done = units.filter((unit) => isComplete(completionOf(unit.id))).length;
        return { ratio: done / units.length, done, total: units.length };
    }, [completionOf, project?.units]);

    const toggleCollapse = (unitId: string) => {
        setCollapsedIds((current) => {
            const next = new Set(current);
            if (next.has(unitId)) next.delete(unitId);
            else next.add(unitId);
            return next;
        });
    };

    const removeUnit = async (unit: UnitNode) => {
        try {
            await deleteUnit.mutateAsync(unit.id);
            if (selectedUnitId === unit.id) setSelectedUnit(null);
            message.success("单元已删除");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col bg-[var(--studio-surface)]">
            <div className="border-b border-[var(--studio-line)] px-3 py-3">
                <Link
                    href="/"
                    className="inline-flex items-center gap-1 text-[11px] text-[var(--studio-faint)] transition-colors hover:text-[var(--studio-ink)]"
                >
                    <ArrowLeft className="size-3.5" />
                    项目列表
                </Link>
                <div className="mt-2 flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                        <h1 className="truncate text-[15px] font-semibold text-[var(--studio-ink)]">
                            {project?.title || "…"}
                        </h1>
                        <div className="mt-0.5 text-[11px] text-[var(--studio-faint)]">
                            {progress.total ? `${progress.done}/${progress.total} 单元完成` : "尚未拆分单元"}
                        </div>
                    </div>
                    <ProgressRing value={progress.ratio} />
                </div>
            </div>

            <div className="flex items-center gap-1.5 border-b border-[var(--studio-line)] px-3 py-2">
                <Input
                    size="small"
                    allowClear
                    value={keyword}
                    onChange={(event) => setKeyword(event.target.value)}
                    prefix={<Search className="size-3.5 text-[var(--studio-faint)]" />}
                    placeholder="搜索单元"
                />
                <Tooltip title="添加章节、场景或镜头">
                    <Button
                        size="small"
                        type="text"
                        aria-label="添加创作单元"
                        icon={<FolderPlus className="size-4" />}
                        onClick={() => setCreateOpen(true)}
                    />
                </Tooltip>
            </div>

            <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-2 py-2">
                <UnitTree
                    nodes={visibleTree}
                    selectedUnitId={selectedUnitId}
                    collapsedIds={collapsedIds}
                    completionOf={completionOf}
                    proposalCountOf={proposalCountOf}
                    onSelect={setSelectedUnit}
                    onToggleCollapse={toggleCollapse}
                    onDelete={(unit) => void removeUnit(unit)}
                />
                {(project?.units.length || 0) === 0 ? (
                    <p className="px-3 py-6 text-center text-[11px] leading-5 text-[var(--studio-faint)]">
                        可以按章节、场景、镜头或任务拆分内容，也可以先不拆，直接和 AI 聊。
                    </p>
                ) : null}
                {keyword && visibleTree.length === 0 ? (
                    <p className="px-3 py-6 text-center text-[11px] text-[var(--studio-faint)]">没有匹配的单元</p>
                ) : null}
            </div>

            <div className="border-t border-[var(--studio-line)] p-2">
                <Link
                    href={hrefFor("brief")}
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px] text-[var(--studio-text)] transition-colors hover:bg-[var(--studio-surface-hover)] hover:text-[var(--studio-ink)]"
                >
                    <BookMarked className="size-4 shrink-0 text-[var(--studio-faint)]" />
                    <span className="min-w-0 flex-1 truncate">创作设定</span>
                    <span className="shrink-0 text-[10px] text-[var(--studio-faint)]">
                        {project?.bible.characters.length ? `${project.bible.characters.length} 角色` : "未建立"}
                    </span>
                </Link>
            </div>

            <UnitCreateModal
                open={createOpen}
                projectId={projectId}
                unitOptions={unitOptions}
                defaultParentId={selectedUnitId}
                orderIndex={project?.units.length || 0}
                onClose={() => setCreateOpen(false)}
                onCreated={setSelectedUnit}
            />
        </div>
    );
}
