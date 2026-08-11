"use client";

import { useEffect, useRef } from "react";
import { BookOpen, FileText, FolderTree } from "lucide-react";

import type { Artifact, CreativeUnit } from "@/services/api";

export type ContextRef = {
    type: "unit" | "artifact" | "bible";
    id?: string;
    section?: string;
    label: string;
};

/** 输入框内 @ 唤起的实体选择器：单元 / 稿件 / 圣经片段。 */
export function MentionPicker({
    units,
    artifacts,
    onPick,
    onClose,
}: {
    units: CreativeUnit[];
    artifacts: Artifact[];
    onPick: (ref: ContextRef) => void;
    onClose: () => void;
}) {
    const containerRef = useRef<HTMLDivElement | null>(null);

    // 打开后聚焦第一项，Esc 关闭（焦点归还由 ContextBar 处理）。
    useEffect(() => {
        containerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [onClose]);

    return (
        <div
            ref={containerRef}
            role="dialog"
            aria-label="选择要加入上下文的引用"
            className="absolute bottom-full left-0 z-30 mb-1 max-h-64 w-72 overflow-y-auto rounded-[var(--r-md)] border border-[var(--hairline-strong)] bg-[var(--s-overlay)] p-1.5 shadow-[var(--s-shadow-md)]"
        >
            <div className="px-2 py-1 text-caption font-medium text-[var(--s-faint)]">创作单元</div>
            {units.length ? (
                units.slice(0, 20).map((unit) => (
                    <button
                        key={unit.id}
                        type="button"
                        onClick={() => onPick({ type: "unit", id: unit.id, label: unit.title })}
                        className="flex w-full items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-label text-[var(--s-muted)] transition-colors hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)]"
                    >
                        <FolderTree className="size-3.5 shrink-0 text-[var(--s-faint)]" />
                        <span className="min-w-0 flex-1 truncate">{unit.title}</span>
                    </button>
                ))
            ) : (
                <div className="px-2 py-1 text-caption text-[var(--s-faint)]">还没有单元</div>
            )}
            <div className="px-2 py-1 text-caption font-medium text-[var(--s-faint)]">稿件</div>
            {artifacts.length ? (
                artifacts.slice(0, 20).map((artifact) => (
                    <button
                        key={artifact.id}
                        type="button"
                        onClick={() => onPick({ type: "artifact", id: artifact.id, label: artifact.name })}
                        className="flex w-full items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-label text-[var(--s-muted)] transition-colors hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)]"
                    >
                        <FileText className="size-3.5 shrink-0 text-[var(--s-faint)]" />
                        <span className="min-w-0 flex-1 truncate">{artifact.name}</span>
                    </button>
                ))
            ) : (
                <div className="px-2 py-1 text-caption text-[var(--s-faint)]">还没有稿件</div>
            )}
            <div className="px-2 py-1 text-caption font-medium text-[var(--s-faint)]">圣经片段</div>
            {[
                { section: "characters", label: "角色设定" },
                { section: "world", label: "世界观" },
                { section: "style", label: "风格设定" },
            ].map((item) => (
                <button
                    key={item.section}
                    type="button"
                    onClick={() => onPick({ type: "bible", section: item.section, label: `圣经 · ${item.label}` })}
                    className="flex w-full items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-label text-[var(--s-muted)] transition-colors hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)]"
                >
                    <BookOpen className="size-3.5 shrink-0 text-[var(--s-faint)]" />
                    <span>{item.label}</span>
                </button>
            ))}
            <button
                type="button"
                onClick={onClose}
                className="mt-1 w-full rounded-[var(--r-sm)] px-2 py-1 text-center text-caption text-[var(--s-faint)] hover:text-[var(--s-ink)]"
            >
                关闭
            </button>
        </div>
    );
}
