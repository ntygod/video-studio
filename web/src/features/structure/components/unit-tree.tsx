"use client";

import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronRight, Layers3, Trash2 } from "lucide-react";

import type { UnitNode } from "@/features/workspace/hooks/use-workspace-data";
import { flattenUnitTree } from "@/features/workspace/hooks/use-workspace-data";
import {
    freshnessMeta,
    type UnitFreshnessSummary,
} from "@/features/workspace/lib/freshness";
import { unitKindLabel } from "@/features/workspace/lib/labels";
import { CompletionDots, type CompletionTriple } from "@/shared/ui/indicators";
import { Popconfirm, StatusDot, Tooltip } from "@/shared/ui";
import { cn } from "@/shared/lib/utils";

export type UnitTreeProps = {
    nodes: UnitNode[];
    selectedUnitId: string | null;
    collapsedIds: Set<string>;
    /** 每个单元的三段完成度，缺省视为全未完成。 */
    completionOf: (unitId: string) => CompletionTriple;
    /** 每个单元的待处理提案数。 */
    proposalCountOf: (unitId: string) => number;
    /** 单元内最严重的过期/阻塞状态。 */
    freshnessOf?: (
        unitId: string,
    ) => UnitFreshnessSummary | null;
    /** 多选集合（Ctrl/Shift 点选）。 */
    multiSelectedIds: Set<string>;
    onSelect: (unitId: string | null) => void;
    onToggleMultiSelect: (unitId: string) => void;
    onToggleCollapse: (unitId: string) => void;
    onDelete: (unit: UnitNode) => void;
    /** 拖拽放置：before/after 为同级重排，child 为改父级。 */
    onDropUnit: (draggedId: string, targetId: string, position: "before" | "after" | "child") => void;
};

/** 单元行左侧缩进的每级像素数。 */
const INDENT = 12;
const ROW_HEIGHT = 38;

type DropState = { targetId: string; position: "before" | "after" | "child" } | null;

function UnitRow({
    node,
    selected,
    multiSelected,
    collapsed,
    completion,
    proposalCount,
    freshness,
    dropState,
    onSelect,
    onToggleMultiSelect,
    onToggleCollapse,
    onDelete,
    onDragStart,
    onDragOver,
    onDrop,
    onDragLeave,
    buttonRef,
    onKeyDown,
}: {
    node: UnitNode;
    selected: boolean;
    multiSelected: boolean;
    collapsed: boolean;
    completion: CompletionTriple;
    proposalCount: number;
    freshness: UnitFreshnessSummary | null;
    dropState: DropState;
    onSelect: () => void;
    onToggleMultiSelect: () => void;
    onToggleCollapse: () => void;
    onDelete: () => void;
    onDragStart: (event: React.DragEvent) => void;
    onDragOver: (event: React.DragEvent) => void;
    onDrop: () => void;
    onDragLeave: () => void;
    buttonRef: React.Ref<HTMLButtonElement>;
    onKeyDown: (event: React.KeyboardEvent) => void;
}) {
    const hasChildren = node.children.length > 0;
    const drop = dropState?.targetId === node.id ? dropState.position : null;
    const statusMeta = freshness
        ? freshnessMeta(freshness.status)
        : null;

    return (
        <div
            draggable
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDrop={(event) => {
                event.preventDefault();
                onDrop();
            }}
            onDragLeave={onDragLeave}
            className={cn(
                "group relative flex items-center rounded-[var(--r-sm)] transition-colors",
                selected || multiSelected
                    ? "bg-[var(--s-raised)]"
                    : "hover:bg-[var(--s-raised)]",
                drop === "before" && "shadow-[inset_0_2px_0_0_var(--s-action)]",
                drop === "after" && "shadow-[inset_0_-2px_0_0_var(--s-action)]",
                drop === "child" && "ring-1 ring-inset ring-[var(--s-action)]",
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
                    "flex size-5 shrink-0 items-center justify-center rounded text-[var(--s-faint)]",
                    hasChildren ? "hover:bg-[var(--s-raised)]" : "invisible",
                )}
            >
                <ChevronRight className={cn("size-3.5 transition-transform", !collapsed && "rotate-90")} />
            </button>

            <button
                type="button"
                ref={buttonRef}
                onClick={(event) => {
                    if (event.ctrlKey || event.metaKey || event.shiftKey) onToggleMultiSelect();
                    else onSelect();
                }}
                onKeyDown={onKeyDown}
                aria-current={selected ? "true" : undefined}
                aria-selected={multiSelected || undefined}
                className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 pr-1 text-left"
            >
                <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                        <span
                            className={cn(
                                "truncate text-body leading-5",
                                selected || multiSelected ? "text-[var(--s-ink)]" : "text-[var(--s-text)]",
                            )}
                        >
                            {node.title}
                        </span>
                        {proposalCount > 0 ? (
                            <Tooltip title={`${proposalCount} 条待处理建议`}>
                                <span className="shrink-0 rounded-full bg-[var(--s-raised)] px-1.5 text-caption font-medium text-[var(--s-ink)]">
                                    {proposalCount}
                                </span>
                            </Tooltip>
                        ) : null}
                    </span>
                    <span className="block truncate text-caption leading-4 text-[var(--s-faint)]">
                        {unitKindLabel(node.unit_type)}
                    </span>
                </span>

                {freshness && statusMeta ? (
                    <Tooltip
                        title={`${statusMeta.label} · ${freshness.count} 份内容`}
                    >
                        <span className="inline-flex shrink-0 items-center gap-1 text-caption text-[var(--s-faint)]">
                            <StatusDot tone={statusMeta.dotTone} />
                            {freshness.count}
                        </span>
                    </Tooltip>
                ) : null}
                <CompletionDots value={completion} className="shrink-0" />
            </button>

            <Popconfirm title="删除此单元及其全部子单元？" okText="删除" cancelText="取消" onConfirm={onDelete}>
                <button
                    type="button"
                    aria-label={`删除 ${node.title}`}
                    className="mr-1 flex size-5 shrink-0 items-center justify-center rounded text-[var(--s-faint)] opacity-0 transition-opacity hover:bg-[var(--s-raised)] hover:text-[var(--s-danger)] group-hover:opacity-100 focus-visible:opacity-100"
                >
                    <Trash2 className="size-3" />
                </button>
            </Popconfirm>
        </div>
    );
}

/**
 * 创作单元树（T3.F1 虚拟化 + T3.F2 拖拽/多选）。
 * <p>
 * 先按折叠状态摊平成前序列表，再用 useVirtualizer 只渲染视口内的行；
 * 上千单元时依旧 60fps。
 */
export function UnitTree({
    nodes,
    selectedUnitId,
    collapsedIds,
    completionOf,
    proposalCountOf,
    freshnessOf = () => null,
    multiSelectedIds,
    onSelect,
    onToggleMultiSelect,
    onToggleCollapse,
    onDelete,
    onDropUnit,
}: UnitTreeProps) {
    const parentRef = useRef<HTMLDivElement>(null);
    const [dropState, setDropState] = useState<DropState>(null);
    const [draggingId, setDraggingId] = useState<string | null>(null);

    const flat = useMemo(() => flattenUnitTree(nodes, collapsedIds), [nodes, collapsedIds]);

    const virtualizer = useVirtualizer({
        count: flat.length + 1, // +1 行 = “整个项目”
        getScrollElement: () => parentRef.current,
        estimateSize: () => ROW_HEIGHT,
        overscan: 12,
    });

    const rootButtonRef = useRef<HTMLButtonElement | null>(null);
    const rowButtonRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map());

    const moveFocusTo = (unitId: string, flatIndex: number) => {
        onSelect(unitId);
        virtualizer.scrollToIndex(flatIndex + 1);
        requestAnimationFrame(() => rowButtonRefs.current.get(unitId)?.focus());
    };

    // T5.2 全键盘：↑/↓ 移动选择，Home/End 首尾，Space 多选，←/→ 折叠/展开。
    const handleRowKeyDown = (event: React.KeyboardEvent, node: UnitNode, flatIndex: number) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const nextIndex = event.key === "ArrowDown" ? flatIndex + 1 : flatIndex - 1;
            if (nextIndex >= 0 && nextIndex < flat.length) {
                const next = flat[nextIndex];
                moveFocusTo(next.id, nextIndex);
            } else if (nextIndex < 0) {
                onSelect(null);
                rootButtonRef.current?.focus();
            }
        } else if (event.key === "Home") {
            event.preventDefault();
            if (flat.length) moveFocusTo(flat[0].id, 0);
        } else if (event.key === "End") {
            event.preventDefault();
            if (flat.length) moveFocusTo(flat[flat.length - 1].id, flat.length - 1);
        } else if (event.key === " ") {
            event.preventDefault();
            onToggleMultiSelect(node.id);
        } else if (event.key === "ArrowRight") {
            if (node.children.length === 0) return;
            event.preventDefault();
            if (collapsedIds.has(node.id)) onToggleCollapse(node.id);
            else if (flatIndex + 1 < flat.length) moveFocusTo(flat[flatIndex + 1].id, flatIndex + 1);
        } else if (event.key === "ArrowLeft") {
            if (node.children.length > 0 && !collapsedIds.has(node.id)) {
                event.preventDefault();
                onToggleCollapse(node.id);
            }
        }
    };

    const handleDragStart = (event: React.DragEvent, node: UnitNode) => {
        event.dataTransfer.setData("text/unit-id", node.id);
        event.dataTransfer.effectAllowed = "move";
        setDraggingId(node.id);
    };

    const handleDragOver = (event: React.DragEvent, node: UnitNode) => {
        event.preventDefault();
        const rect = event.currentTarget.getBoundingClientRect();
        const ratio = (event.clientY - rect.top) / rect.height;
        const position: "before" | "after" | "child" = ratio < 0.3 ? "before" : ratio > 0.7 ? "after" : "child";
        setDropState((current) =>
            current?.targetId === node.id && current.position === position ? current : { targetId: node.id, position },
        );
    };

    return (
        <div className="flex h-full min-h-0 flex-col">
            <button
                type="button"
                ref={rootButtonRef}
                onClick={() => onSelect(null)}
                aria-current={selectedUnitId === null ? "true" : undefined}
                onDragOver={(event) => {
                    event.preventDefault();
                    setDropState({ targetId: "__root__", position: "child" });
                }}
                onDragLeave={() => setDropState(null)}
                onDrop={(event) => {
                    event.preventDefault();
                    if (draggingId) onDropUnit(draggingId, "__root__", "child");
                    setDraggingId(null);
                    setDropState(null);
                }}
                className={cn(
                    "mb-1 flex w-full shrink-0 items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-body transition-colors",
                    selectedUnitId === null
                        ? "bg-[var(--s-raised)] text-[var(--s-ink)]"
                        : "text-[var(--s-text)] hover:bg-[var(--s-raised)]",
                    dropState?.targetId === "__root__" && "ring-1 ring-inset ring-[var(--s-action)]",
                )}
            >
                <Layers3 className="size-4 shrink-0 text-[var(--s-faint)]" />
                整个项目
            </button>

            <div ref={parentRef} className="hide-scrollbar min-h-0 flex-1 overflow-y-auto">
                <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
                    {virtualizer.getVirtualItems().map((virtualRow) => {
                        if (virtualRow.index === 0) {
                            return (
                                <div
                                    key="__root__"
                                    className="px-2 py-1 text-caption text-[var(--s-faint)]"
                                    style={{
                                        position: "absolute",
                                        top: 0,
                                        left: 0,
                                        width: "100%",
                                        height: virtualRow.size,
                                        transform: `translateY(${virtualRow.start}px)`,
                                    }}
                                >
                                    {flat.length} 个单元
                                </div>
                            );
                        }
                        const node = flat[virtualRow.index - 1];
                        if (!node) return null;
                        return (
                            <div
                                key={node.id}
                                className="px-1"
                                style={{
                                    position: "absolute",
                                    top: 0,
                                    left: 0,
                                    width: "100%",
                                    height: virtualRow.size,
                                    transform: `translateY(${virtualRow.start}px)`,
                                }}
                            >
                                <UnitRow
                                    node={node}
                                    selected={selectedUnitId === node.id}
                                    multiSelected={multiSelectedIds.has(node.id)}
                                    collapsed={collapsedIds.has(node.id)}
                                    completion={completionOf(node.id)}
                                    proposalCount={proposalCountOf(node.id)}
                                    freshness={freshnessOf(node.id)}
                                    dropState={dropState}
                                    onSelect={() => onSelect(node.id)}
                                    onToggleMultiSelect={() => onToggleMultiSelect(node.id)}
                                    onToggleCollapse={() => onToggleCollapse(node.id)}
                                    onDelete={() => onDelete(node)}
                                    onDragStart={(event) => handleDragStart(event, node)}
                                    onDragOver={(event) => handleDragOver(event, node)}
                                    onDragLeave={() => setDropState(null)}
                                    onDrop={() => {
                                        if (draggingId && draggingId !== node.id && dropState) {
                                            onDropUnit(draggingId, node.id, dropState.position);
                                        }
                                        setDraggingId(null);
                                        setDropState(null);
                                    }}
                                    buttonRef={(element) => {
                                        rowButtonRefs.current.set(node.id, element);
                                    }}
                                    onKeyDown={(event) => handleRowKeyDown(event, node, virtualRow.index - 1)}
                                />
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
