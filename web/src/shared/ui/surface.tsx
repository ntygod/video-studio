"use client";

import type { ElementType, HTMLAttributes } from "react";

import { cn } from "@/shared/lib/utils";

export type SurfaceLevel = "canvas" | "base" | "panel" | "raised" | "overlay";

const LEVEL_CLASS: Record<SurfaceLevel, string> = {
    canvas: "bg-[var(--s-canvas)]",
    base: "bg-[var(--s-base)]",
    panel: "bg-[var(--s-panel)]",
    raised: "bg-[var(--s-raised)]",
    overlay: "bg-[var(--s-overlay)]",
};

const INSET_CLASS = {
    none: "",
    "1": "p-[var(--sp-1)]",
    "2": "p-[var(--sp-2)]",
    "3": "p-[var(--sp-3)]",
    "4": "p-[var(--sp-4)]",
    "6": "p-[var(--sp-6)]",
} as const;

const RADIUS_CLASS = {
    none: "",
    xs: "rounded-[var(--r-xs)]",
    sm: "rounded-[var(--r-sm)]",
    md: "rounded-[var(--r-md)]",
    lg: "rounded-[var(--r-lg)]",
} as const;

/**
 * 容器基元：封装表面层级，让"画错"在物理上不可能。
 * <p>
 * 规则：同层不画线，只有跨层级才用 hairline；卡片靠 panel + lift 浮起来。
 */
export function Surface({
    as: Tag = "div",
    level = "panel",
    inset = "none",
    radius = "md",
    lift = false,
    hairline = false,
    hairlineStrong = false,
    className,
    ...props
}: {
    as?: ElementType;
    level?: SurfaceLevel;
    inset?: keyof typeof INSET_CLASS;
    radius?: keyof typeof RADIUS_CLASS;
    lift?: boolean;
    hairline?: boolean;
    hairlineStrong?: boolean;
} & HTMLAttributes<HTMLElement>) {
    return (
        <Tag
            className={cn(
                LEVEL_CLASS[level],
                RADIUS_CLASS[radius],
                INSET_CLASS[inset],
                lift && "shadow-[var(--lift)]",
                hairline && "border border-[var(--hairline)]",
                hairlineStrong && "border border-[var(--hairline-strong)]",
                className,
            )}
            {...props}
        />
    );
}
