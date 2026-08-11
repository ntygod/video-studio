"use client";

import { cn } from "@/shared/lib/utils";

/**
 * 分隔线：全站唯一允许画线的基元。
 */
export function Divider({
    strong = false,
    vertical = false,
    className,
}: {
    strong?: boolean;
    vertical?: boolean;
    className?: string;
}) {
    return (
        <div
            role="separator"
            aria-orientation={vertical ? "vertical" : "horizontal"}
            className={cn(
                vertical ? "w-px shrink-0 self-stretch" : "h-px w-full",
                strong ? "bg-[var(--hairline-strong)]" : "bg-[var(--hairline)]",
                className,
            )}
        />
    );
}
