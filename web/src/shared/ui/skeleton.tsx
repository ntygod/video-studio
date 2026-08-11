"use client";

import { cn } from "@/shared/lib/utils";

/**
 * 骨架屏：text / media / card 三种，shimmer 与真实布局对齐。
 */
export function Skeleton({
    variant = "text",
    className,
}: {
    variant?: "text" | "media" | "card";
    className?: string;
}) {
    if (variant === "media") {
        return <div className={cn("s-shimmer aspect-video rounded-[var(--r-xs)]", className)} />;
    }
    if (variant === "card") {
        return (
            <div className={cn("rounded-[var(--r-md)] bg-[var(--s-panel)] p-[var(--sp-3)] shadow-[var(--lift)]", className)}>
                <div className="s-shimmer aspect-video rounded-[var(--r-xs)]" />
                <div className="s-shimmer mt-[var(--sp-3)] h-3 w-3/4 rounded" />
                <div className="s-shimmer mt-[var(--sp-2)] h-2.5 w-1/2 rounded" />
            </div>
        );
    }
    return <div className={cn("s-shimmer h-3 w-full rounded", className)} />;
}
