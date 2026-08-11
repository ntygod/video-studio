"use client";

import { cn } from "@/shared/lib/utils";

/**
 * 线性进度：单色（--s-ink），不抢内容。
 */
export function Progress({
    value,
    indeterminate = false,
    className,
}: {
    value?: number;
    indeterminate?: boolean;
    className?: string;
}) {
    const clamped = Math.max(0, Math.min(1, value ?? 0));
    return (
        <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={indeterminate ? undefined : Math.round(clamped * 100)}
            className={cn("h-1 w-full overflow-hidden rounded-full bg-[var(--s-raised)]", className)}
        >
            {indeterminate ? (
                <div className="s-shimmer h-full w-1/3 rounded-full" />
            ) : (
                <div
                    className="h-full rounded-full bg-[var(--s-ink)] transition-[width] duration-[var(--dur-slow)] ease-[var(--ease-out)]"
                    style={{ width: `${clamped * 100}%` }}
                />
            )}
        </div>
    );
}
