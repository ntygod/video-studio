"use client";

import type { HTMLAttributes } from "react";

import { cn } from "@/shared/lib/utils";

const GAP_CLASS = {
    "1": "gap-[var(--sp-1)]",
    "2": "gap-[var(--sp-2)]",
    "3": "gap-[var(--sp-3)]",
    "4": "gap-[var(--sp-4)]",
    "6": "gap-[var(--sp-6)]",
    "8": "gap-[var(--sp-8)]",
} as const;

const ALIGN_CLASS = {
    start: "items-start",
    center: "items-center",
    end: "items-end",
    stretch: "items-stretch",
    baseline: "items-baseline",
} as const;

const JUSTIFY_CLASS = {
    start: "justify-start",
    center: "justify-center",
    end: "justify-end",
    between: "justify-between",
    around: "justify-around",
} as const;

/**
 * 布局基元：强制走 4px 基线间距梯度。
 */
export function Stack({
    dir = "col",
    gap = "2",
    align,
    justify,
    wrap = false,
    className,
    ...props
}: {
    dir?: "row" | "col";
    gap?: keyof typeof GAP_CLASS;
    align?: keyof typeof ALIGN_CLASS;
    justify?: keyof typeof JUSTIFY_CLASS;
    wrap?: boolean;
} & HTMLAttributes<HTMLDivElement>) {
    return (
        <div
            className={cn(
                "flex",
                dir === "col" ? "flex-col" : "flex-row",
                GAP_CLASS[gap],
                align && ALIGN_CLASS[align],
                justify && JUSTIFY_CLASS[justify],
                wrap && "flex-wrap",
                className,
            )}
            {...props}
        />
    );
}
