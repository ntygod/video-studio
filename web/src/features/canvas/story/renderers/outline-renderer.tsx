"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { BlockActions } from "./block-actions";
import { cn } from "@/shared/lib/utils";

type OutlineNode = {
    title?: string;
    heading?: string;
    summary?: string;
    children?: OutlineNode[];
    sections?: OutlineNode[];
};

function toChildren(node: OutlineNode): OutlineNode[] {
    const raw = node.children ?? node.sections;
    return Array.isArray(raw) ? (raw as OutlineNode[]) : [];
}

function OutlineItem({ node, depth, onRewrite }: { node: OutlineNode; depth: number; onRewrite: (text: string) => void }) {
    const [collapsed, setCollapsed] = useState(false);
    const title = node.title || node.heading || "未命名";
    const children = toChildren(node);
    return (
        <div>
            <div
                className={cn("flex items-start gap-1 rounded-md py-1 hover:bg-[var(--s-raised)]")}
                style={{ paddingLeft: depth * 16 }}
            >
                {children.length ? (
                    <button
                        type="button"
                        aria-label={collapsed ? "展开" : "折叠"}
                        onClick={() => setCollapsed((current) => !current)}
                        className="mt-0.5 flex size-4 shrink-0 items-center justify-center text-[var(--s-faint)]"
                    >
                        <ChevronRight className={cn("size-3 transition-transform", !collapsed && "rotate-90")} />
                    </button>
                ) : (
                    <span className="size-4 shrink-0" />
                )}
                <BlockActions text={title} onRewrite={onRewrite} />
                <span className="min-w-0 flex-1 text-body leading-6 text-[var(--s-ink)]">{title}</span>
                {node.summary ? (
                    <span className="hidden max-w-[40%] truncate text-caption text-[var(--s-faint)] sm:inline">{node.summary}</span>
                ) : null}
            </div>
            {!collapsed && children.length ? (
                <div>
                    {children.map((child, index) => (
                        <OutlineItem key={index} node={child} depth={depth + 1} onRewrite={onRewrite} />
                    ))}
                </div>
            ) : null}
        </div>
    );
}

/** 大纲渲染器：可折叠嵌套大纲。 */
export function OutlineRenderer({ payload, onRewrite }: { payload: Record<string, unknown>; onRewrite: (text: string) => void }) {
    const rawRoots = payload.sections ?? payload.children;
    const roots = Array.isArray(rawRoots) ? (rawRoots as OutlineNode[]) : [];
    if (!roots.length) {
        return <div className="py-8 text-center text-label text-[var(--s-faint)]">大纲还没有内容</div>;
    }
    return (
        <div className="rounded-lg border border-[var(--hairline)] p-3">
            {roots.map((node, index) => (
                <OutlineItem key={index} node={node} depth={0} onRewrite={onRewrite} />
            ))}
        </div>
    );
}
