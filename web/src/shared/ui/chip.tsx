"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { cn } from "@/shared/lib/utils";

export type ChipTone = "default" | "accent" | "success" | "warning" | "danger" | "info";

const TONE_CLASS: Record<ChipTone, string> = {
    default: "bg-[var(--s-raised)] text-[var(--s-text)]",
    accent: "border border-[var(--s-action-line)] text-[var(--s-action)]",
    success: "border border-[color-mix(in_srgb,var(--s-success)_45%,transparent)] text-[var(--s-success)]",
    warning: "border border-[color-mix(in_srgb,var(--s-warning)_45%,transparent)] text-[var(--s-warning)]",
    danger: "border border-[color-mix(in_srgb,var(--s-danger)_45%,transparent)] text-[var(--s-danger)]",
    info: "border border-[color-mix(in_srgb,var(--s-info)_45%,transparent)] text-[var(--s-info)]",
};

/**
 * 标签/状态 chip。语义色只做文字 + 1px 描边，不做大面积填充。
 */
export function Chip({
    tone = "default",
    removable = false,
    onRemove,
    onClick,
    label,
    children,
    className,
}: {
    tone?: ChipTone;
    removable?: boolean;
    onRemove?: () => void;
    onClick?: () => void;
    label?: string;
    children: ReactNode;
    className?: string;
}) {
    const Root = onClick ? "button" : "span";
    return (
        <Root
            type={onClick ? "button" : undefined}
            onClick={onClick}
            className={cn(
                "inline-flex h-6 max-w-full items-center gap-1 rounded-[var(--r-xs)] px-2 text-caption font-medium",
                TONE_CLASS[tone],
                onClick && "cursor-pointer transition-colors hover:text-[var(--s-ink)]",
                className,
            )}
        >
            <span className="truncate">{children}</span>
            {removable ? (
                <button
                    type="button"
                    aria-label={label ? `移除 ${label}` : "移除"}
                    onClick={onRemove}
                    className="-mr-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-black/10 dark:hover:bg-white/10"
                >
                    <X className="size-3" />
                </button>
            ) : null}
        </Root>
    );
}
