"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderPlus, Search, Sparkles } from "lucide-react";

import { BiblePanelButton } from "@/features/structure/components/bible-panel";
import { UnitCreateModal } from "@/features/structure/components/unit-create-modal";
import { UnitTree } from "@/features/structure/components/unit-tree";
import { useWorkspaceData, type UnitNode } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { freshnessByUnit } from "@/features/workspace/lib/freshness";
import { isContentArtifactKind, unitKindLabel } from "@/features/workspace/lib/labels";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import {
    useAssets,
    useDeleteUnit,
    useProjectArtifactFreshness,
    useSearch,
    useUpdateUnit,
} from "@/services/queries";
import { type CompletionTriple } from "@/shared/ui/indicators";
import { Button, Input, Select, Text, Tooltip, useApp } from "@/shared/ui";
import { cn } from "@/shared/lib/utils";

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

type FilterKey = "all" | "attention" | "incomplete" | "proposals" | "locked";

const FILTERS: Array<{ key: FilterKey; label: string }> = [
    { key: "all", label: "全部" },
    { key: "attention", label: "需处理" },
    { key: "incomplete", label: "未完成" },
    { key: "proposals", label: "有提案" },
    { key: "locked", label: "已锁定" },
];

/**
 * 左侧结构导航（T3.F2 增强）。
 * <p>
 * 单元树虚拟化；支持筛选（需处理/未完成/有提案/已锁定/类型）、FTS 搜索、
 * 拖拽重排与改父级、Ctrl/Shift 多选后批量交给 Agent。
 */
export function StructurePanel() {
    const { message } = useApp();
    const { projectId, selectedUnitId, setSelectedUnit } = useWorkspaceRoute();
    const { project, units, unitTree, unitOptions, artifacts, pendingProposals } = useWorkspaceData();

    // 完成度需要项目全域的素材，与画布里按单元过滤的那份是不同的 query key。
    const allAssets = useAssets(projectId, null);
    const freshnessQuery = useProjectArtifactFreshness(projectId);
    const deleteUnit = useDeleteUnit(projectId);
    const updateUnit = useUpdateUnit(projectId);
    const pushContextRefs = useWorkspaceStore((state) => state.pushContextRefs);
    const unitCreateRequested = useWorkspaceStore((state) => state.unitCreateRequested);

    // ⌘K 命令面板的「新建创作单元」落到这里打开弹窗。
    useEffect(() => {
        if (unitCreateRequested > 0) setCreateOpen(true);
    }, [unitCreateRequested]);

    const [keyword, setKeyword] = useState("");
    const [filter, setFilter] = useState<FilterKey>("all");
    const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);
    const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
    const [multiSelectedIds, setMultiSelectedIds] = useState<Set<string>>(new Set());
    const [createOpen, setCreateOpen] = useState(false);

    const searchQuery = useSearch(projectId, keyword);

    const artifactUnitIds = useMemo(() => {
        const ids = new Set<string>();
        (artifacts || []).forEach((artifact) => {
            if (artifact.unit_id && isContentArtifactKind(artifact.kind)) ids.add(artifact.unit_id);
        });
        return ids;
    }, [artifacts]);

    const lockedUnitIds = useMemo(() => {
        const ids = new Set<string>();
        (artifacts || []).forEach((artifact) => {
            if (artifact.unit_id && artifact.current_version?.status === "locked") ids.add(artifact.unit_id);
        });
        return ids;
    }, [artifacts]);

    const unitFreshness = useMemo(
        () => freshnessByUnit(freshnessQuery.data?.items || []),
        [freshnessQuery.data?.items],
    );

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
        (pendingProposals || []).forEach((proposal) => {
            if (!proposal.unit_id) return;
            counts.set(proposal.unit_id, (counts.get(proposal.unit_id) || 0) + 1);
        });
        return counts;
    }, [pendingProposals]);

    const unitTypes = useMemo(() => [...new Set(units.map((unit) => unit.unit_type))].sort(), [units]);

    const completionOf = useCallback((unitId: string): CompletionTriple => [artifactUnitIds.has(unitId), assetUnitIds.media.has(unitId), assetUnitIds.renders.has(unitId)], [artifactUnitIds, assetUnitIds]);

    const proposalCountOf = useCallback((unitId: string) => proposalCounts.get(unitId) || 0, [proposalCounts]);

    const freshnessOf = useCallback(
        (unitId: string) => unitFreshness.get(unitId) || null,
        [unitFreshness],
    );

    const visibleTree = useMemo(() => {
        let tree = unitTree;
        if (filter === "attention") {
            tree = filterTree(tree, (node) => unitFreshness.has(node.id));
        } else if (filter === "incomplete") {
            tree = filterTree(tree, (node) => !isComplete(completionOf(node.id)));
        } else if (filter === "proposals") {
            tree = filterTree(tree, (node) => proposalCountOf(node.id) > 0);
        } else if (filter === "locked") {
            tree = filterTree(tree, (node) => lockedUnitIds.has(node.id));
        }
        if (typeFilter) {
            tree = filterTree(tree, (node) => node.unit_type === typeFilter);
        }
        return tree;
    }, [unitTree, filter, typeFilter, completionOf, proposalCountOf, lockedUnitIds, unitFreshness]);

    const searching = keyword.trim().length > 0;
    const searchHits = searching ? searchQuery.data || [] : [];

    const progress = useMemo(() => {
        if (!units.length) return { ratio: 0, done: 0, total: 0 };
        const done = units.filter((unit) => isComplete(completionOf(unit.id))).length;
        return { ratio: done / units.length, done, total: units.length };
    }, [completionOf, units]);

    const toggleCollapse = (unitId: string) => {
        setCollapsedIds((current) => {
            const next = new Set(current);
            if (next.has(unitId)) next.delete(unitId);
            else next.add(unitId);
            return next;
        });
    };

    const toggleMultiSelect = (unitId: string) => {
        setMultiSelectedIds((current) => {
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

    const allUnitNodes = useMemo(() => {
        const map = new Map<string, UnitNode>();
        const walk = (list: UnitNode[]) =>
            list.forEach((node) => {
                map.set(node.id, node);
                walk(node.children);
            });
        walk(unitTree);
        return map;
    }, [unitTree]);

    const dropUnit = async (draggedId: string, targetId: string, position: "before" | "after" | "child") => {
        const dragged = allUnitNodes.get(draggedId);
        if (!dragged) return;
        let parentId: string | null;
        let orderIndex: number;
        if (targetId === "__root__") {
            parentId = null;
            orderIndex = Math.max(0, ...units.filter((unit) => !unit.parent_id).map((unit) => unit.order_index)) + 1;
        } else {
            const target = allUnitNodes.get(targetId);
            if (!target) return;
            if (position === "child") {
                parentId = target.id;
                const siblings = units.filter((unit) => unit.parent_id === target.id).map((unit) => unit.order_index);
                orderIndex = (siblings.length ? Math.max(...siblings) : 0) + 1;
            } else {
                parentId = target.parent_id;
                orderIndex = position === "before" ? target.order_index - 1 : target.order_index + 1;
            }
        }
        if (dragged.parent_id === parentId && dragged.order_index === orderIndex) return;
        try {
            await updateUnit.mutateAsync({ unitId: draggedId, patch: { parent_id: parentId, order_index: orderIndex } });
            message.success(position === "child" ? "已改为子单元" : "已重排");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "排序保存失败");
        }
    };

    const handToAgent = () => {
        const refs = [...multiSelectedIds]
            .map((id) => allUnitNodes.get(id))
            .filter((node): node is UnitNode => Boolean(node))
            .map((node) => ({ type: "unit", id: node.id, label: node.title }));
        if (!refs.length) return;
        pushContextRefs(refs);
        setMultiSelectedIds(new Set());
        message.success(`已把 ${refs.length} 个单元加入助手上下文`);
    };

    return (
        <div className="flex h-full min-h-0 flex-col bg-[var(--s-panel)]">
            <div className="border-b border-[var(--hairline)] px-3 py-4">
                <Text as="h1" variant="heading" tone="ink" truncate>
                    {project?.title || "…"}
                </Text>
                <div className="mt-1 flex items-center justify-between gap-2">
                    <Text variant="caption" tone="faint" truncate>
                        {progress.total ? `${progress.done}/${progress.total} 单元已准备` : "尚未拆分单元"}
                    </Text>
                    <Text variant="mono" tone="faint">
                        {Math.round(progress.ratio * 100)}%
                    </Text>
                </div>
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--s-raised)]">
                    <span className="block h-full rounded-full bg-[var(--s-action)]" style={{ width: `${progress.ratio * 100}%` }} />
                </div>
            </div>

            <div className="space-y-1.5 border-b border-[var(--hairline)] px-3 py-2">
                <div className="flex items-center gap-1.5">
                    <Input size="small" allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} prefix={<Search className="size-3.5 text-[var(--s-faint)]" />} placeholder="搜索结构与稿件" />
                    <Tooltip title="添加章节、场景或镜头">
                        <Button size="sm" variant="ghost" aria-label="添加创作单元" icon={<FolderPlus className="size-4" />} onClick={() => setCreateOpen(true)} />
                    </Tooltip>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {FILTERS.map((item) => (
                        <button
                            key={item.key}
                            type="button"
                            onClick={() => setFilter(item.key)}
                            className={cn(
                                "rounded-full border px-2 py-0.5 text-caption transition-colors",
                                filter === item.key ? "border-transparent bg-[var(--s-raised)] text-[var(--s-ink)]" : "border-[var(--hairline)] text-[var(--s-faint)] hover:text-[var(--s-ink)]",
                            )}
                        >
                            {item.label}
                        </button>
                    ))}
                    {unitTypes.length > 1 ? <Select size="small" allowClear placeholder="类型" className="min-w-[92px]" value={typeFilter} onChange={setTypeFilter} options={unitTypes.map((type) => ({ value: type, label: unitKindLabel(type) }))} /> : null}
                    {multiSelectedIds.size > 0 ? (
                        <Button size="sm" variant="primary" className="!ml-auto" icon={<Sparkles className="size-3" />} onClick={handToAgent}>
                            交给 Agent（{multiSelectedIds.size}）
                        </Button>
                    ) : null}
                </div>
            </div>

            <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-2 py-2">
                {searching ? (
                    searchQuery.isLoading ? (
                        <p className="px-3 py-6 text-center text-caption text-[var(--s-faint)]">搜索中…</p>
                    ) : searchHits.length === 0 ? (
                        <p className="px-3 py-6 text-center text-caption text-[var(--s-faint)]">没有匹配结果</p>
                    ) : (
                        <div className="space-y-0.5">
                            {searchHits.map((hit) => (
                                <button
                                    key={`${hit.type}:${hit.id}`}
                                    type="button"
                                    onClick={() => {
                                        if (hit.type === "unit") setSelectedUnit(hit.id);
                                        else if (hit.unit_id) setSelectedUnit(hit.unit_id);
                                    }}
                                    className="w-full rounded-[var(--r-sm)] px-2 py-1.5 text-left transition-colors hover:bg-[var(--s-raised)]"
                                >
                                    <span className="flex items-center gap-1.5 text-label text-[var(--s-ink)]">
                                        <span className="rounded bg-[var(--s-raised)] px-1 text-caption text-[var(--s-faint)]">{hit.type === "unit" ? "单元" : "稿件"}</span>
                                        {hit.title}
                                    </span>
                                    <span className="block truncate text-caption text-[var(--s-faint)]">{hit.snippet}</span>
                                </button>
                            ))}
                        </div>
                    )
                ) : (
                    <UnitTree
                        nodes={visibleTree}
                        selectedUnitId={selectedUnitId}
                        collapsedIds={collapsedIds}
                        completionOf={completionOf}
                        proposalCountOf={proposalCountOf}
                        freshnessOf={freshnessOf}
                        multiSelectedIds={multiSelectedIds}
                        onSelect={setSelectedUnit}
                        onToggleMultiSelect={toggleMultiSelect}
                        onToggleCollapse={toggleCollapse}
                        onDelete={(unit) => void removeUnit(unit)}
                        onDropUnit={(draggedId, targetId, position) => void dropUnit(draggedId, targetId, position)}
                    />
                )}
                {!searching && units.length === 0 ? <p className="px-3 py-6 text-center text-caption leading-5 text-[var(--s-faint)]">可以按章节、场景、镜头或任务拆分内容，也可以先不拆，直接和 AI 聊。</p> : null}
            </div>

            <div className="border-t border-[var(--hairline)] p-2">
                <BiblePanelButton />
            </div>

            <UnitCreateModal open={createOpen} projectId={projectId} unitOptions={unitOptions} defaultParentId={selectedUnitId} orderIndex={units.length || 0} onClose={() => setCreateOpen(false)} onCreated={setSelectedUnit} />
        </div>
    );
}
