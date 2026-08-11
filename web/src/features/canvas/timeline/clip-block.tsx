"use client";

import { useRef } from "react";
import { GripVertical } from "lucide-react";

import type { TimelineClip } from "./types";
import { cn } from "@/shared/lib/utils";

/**
 * 片段块（T4.F1）：拖动主体改起点，拖右缘改时长。
 * 自绘 div + transform，不引第三方时间线库。
 */
export function ClipBlock({ clip, trackKind, pxPerSec, selected, onSelect, onChange }: { clip: TimelineClip; trackKind: string; pxPerSec: number; selected: boolean; onSelect: () => void; onChange: (clip: TimelineClip) => void }) {
    const dragRef = useRef<{ mode: "move" | "resize"; startX: number; baseStart: number; baseDuration: number } | null>(null);

    const beginDrag = (mode: "move" | "resize") => (event: React.PointerEvent) => {
        event.preventDefault();
        event.stopPropagation();
        dragRef.current = {
            mode,
            startX: event.clientX,
            baseStart: clip.range.start,
            baseDuration: clip.range.duration,
        };
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        onSelect();
    };

    const handleMove = (event: React.PointerEvent) => {
        const drag = dragRef.current;
        if (!drag) return;
        const delta = (event.clientX - drag.startX) / pxPerSec;
        if (drag.mode === "move") {
            onChange({
                ...clip,
                range: { ...clip.range, start: Math.max(0, Math.round((drag.baseStart + delta) * 100) / 100) },
            });
        } else {
            onChange({
                ...clip,
                range: {
                    ...clip.range,
                    duration: Math.max(0.2, Math.round((drag.baseDuration + delta) * 100) / 100),
                },
            });
        }
    };

    const endDrag = () => {
        dragRef.current = null;
    };

    const left = clip.range.start * pxPerSec;
    const width = Math.max(12, clip.range.duration * pxPerSec);
    const clipColor = ["voice", "music", "sfx"].includes(trackKind) ? "var(--s-brand-end)" : trackKind === "subtitle" ? "var(--s-warning)" : "var(--s-info)";

    return (
        <div
            role="button"
            tabIndex={0}
            aria-label={`片段 ${clip.metadata?.unit_id || clip.asset_id || clip.id}，${clip.range.start.toFixed(1)}s 起`}
            onPointerDown={beginDrag("move")}
            onPointerMove={handleMove}
            onPointerUp={endDrag}
            onClick={(event) => {
                event.stopPropagation();
                onSelect();
            }}
            className={cn("absolute top-1 flex h-10 cursor-grab touch-none select-none items-center overflow-hidden rounded-[var(--r-sm)] border px-1.5 text-caption active:cursor-grabbing", selected ? "font-medium" : "opacity-90 hover:opacity-100")}
            style={{
                left,
                width,
                transform: "translateX(0)",
                color: clipColor,
                borderColor: `color-mix(in srgb, ${clipColor} 44%, var(--hairline))`,
                backgroundColor: `color-mix(in srgb, ${clipColor} 12%, var(--s-raised))`,
                boxShadow: selected ? "inset 0 0 0 1px currentColor" : undefined,
            }}
        >
            {selected ? <span aria-hidden className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-action)]" /> : null}
            <span className="min-w-0 flex-1 truncate">{String(clip.metadata?.unit_id || clip.asset_id || "").slice(0, 10)}</span>
            <span
                role="slider"
                aria-label="调整片段时长"
                aria-valuemin={0.2}
                aria-valuenow={clip.range.duration}
                aria-valuemax={60}
                onPointerDown={beginDrag("resize")}
                className="flex h-full w-3 shrink-0 cursor-ew-resize touch-none items-center justify-center border-l border-[var(--hairline-strong)] text-[var(--s-faint)] hover:text-[var(--s-ink)]"
            >
                <GripVertical className="size-2.5" />
            </span>
        </div>
    );
}
