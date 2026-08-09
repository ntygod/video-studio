"use client";

import { Popconfirm, Tooltip } from "antd";
import { ChevronRight, Layers3, Trash2 } from "lucide-react";

import type { UnitNode } from "@/features/workspace/hooks/use-workspace-data";
import { unitKindLabel } from "@/features/workspace/lib/labels";
import { CompletionDots, type CompletionTriple } from "@/shared/ui/indicators";
import { cn } from "@/shared/lib/utils";

export type UnitTreeProps = {
    nodes: UnitNode[];
    selectedUnitId: string | null;
    collapsedIds: Set<string>;
    /** 每个单元的三段完成度，缺省视为全未完成。 */
    completionOf: (unitId: string) => CompletionTriple;
    /** 每个单元的待处理提案数。 */
    proposalCountOf: (unitId: string) => number;
    onSelect: (unitId: string | null) => void;
    onToggleCollapse: (unitId: string) => void;
    onDelete: (unit: UnitNode) => void;
};

/** 单元行左侧缩进的每级像素数。 */
const INDENT = 12;

function UnitRow({
    node,
    selected,
    collapsed,
    completion,
    proposalCount,
    onSelect,
    onToggleCollapse,
    onDelete,
}: {
    node: UnitNode;
    selected: boolean;
    collapsed: boolean;
    completion: CompletionTriple;
    proposalCount: number;
    onSelect: () => void;
    onToggleCollapse: () => void;
    onDelete: () => void;
}) {
    const hasChildren = node.children.length > 0;

    return (
        <div
            className={cn(
                "group flex items-center rounded-md transition-colors",
                selected ? "bg-[var(--studio-action-soft)]" : "hover:bg-[var(--studio-surface-hover)]",
            )}
            style={{ paddingLeft: 4 + node.depth * INDENT }}
        >
            <button
                type="button"
                aria-label={collapsed ? `展开 ${node.title}` : `折叠 ${node.title}`}
                aria-expanded={hasChildren ? !collapsed : undefined}
                disabled={!hasChildren}
                onClick={onToggleCollapse}
                className={cn(
                    "flex size-5 shrink-0 items-center justify-center rounded text-[var(--studio-faint)]",
                    hasChildren ? "hover:bg-[var(--studio-surface-raised)]" : "invisible",
                )}
            >
                <ChevronRight className={cn("size-3.5 transition-transform", !collapsed && "rotate-90")} />
            </button>

            <button
                type="button"
                onClick={onSelect}
                aria-current={selected ? "true" : undefined}
                className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 pr-1 text-left"
            >
                <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                        <span
                            className={cn(
                                "truncate text-[13px] leading-5",
                                selected ? "text-[var(--studio-ink)]" : "text-[var(--studio-text)]",
                            )}
                        >
                            {node.title}
                        </span>
                        {proposalCount > 0 ? (
                            <Tooltip title={`${proposalCount} 条待处理建议`}>
                                <span className="shrink-0 rounded-full bg-[var(--studio-action-soft)] px-1.5 text-[10px] font-medium text-[var(--studio-action-emphasis)]">
                                    {proposalCount}
                                </span>
                            </Tooltip>
                        ) : null}
                    </span>
                    <span className="block truncate text-[10px] leading-4 text-[var(--studio-faint)]">
                        {unitKindLabel(node.unit_type)}
                    </span>
                </span>

                <CompletionDots value={completion} className="shrink-0" />
            </button>

            <Popconfirm title="删除此单元及其全部子单元？" okText="删除" cancelText="取消" onConfirm={onDelete}>
                <button
                    type="button"
                    aria-label={`删除 ${node.title}`}
                    className="mr-1 flex size-5 shrink-0 items-center justify-center rounded text-[var(--studio-faint)] opacity-0 transition-opacity hover:bg-[var(--studio-surface-raised)] hover:text-[var(--studio-danger)] group-hover:opacity-100 focus-visible:opacity-100"
                >
                    <Trash2 className="size-3" />
                </button>
            </Popconfirm>
        </div>
    );
}

/**
 * 创作单元树。
 * <p>
 * 递归渲染。单元数量上千时需要换成虚拟化列表（P3），当前先保证结构与交互正确。
 */
export function UnitTree({
    nodes,
    selectedUnitId,
    collapsedIds,
    completionOf,
    proposalCountOf,
    onSelect,
    onToggleCollapse,
    onDelete,
}: UnitTreeProps) {
    const renderNodes = (list: UnitNode[]) =>
        list.map((node) => (
            <div key={node.id}>
                <UnitRow
                    node={node}
                    selected={selectedUnitId === node.id}
                    collapsed={collapsedIds.has(node.id)}
                    completion={completionOf(node.id)}
                    proposalCount={proposalCountOf(node.id)}
                    onSelect={() => onSelect(node.id)}
                    onToggleCollapse={() => onToggleCollapse(node.id)}
                    onDelete={() => onDelete(node)}
                />
                {!collapsedIds.has(node.id) && node.children.length ? renderNodes(node.children) : null}
            </div>
        ));

    return (
        <div className="space-y-px">
            <button
                type="button"
                onClick={() => onSelect(null)}
                aria-current={selectedUnitId === null ? "true" : undefined}
                className={cn(
                    "mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors",
                    selectedUnitId === null
                        ? "bg-[var(--studio-action-soft)] text-[var(--studio-ink)]"
                        : "text-[var(--studio-text)] hover:bg-[var(--studio-surface-hover)]",
                )}
            >
                <Layers3 className="size-4 shrink-0 text-[var(--studio-faint)]" />
                整个项目
            </button>
            {renderNodes(nodes)}
        </div>
    );
}
