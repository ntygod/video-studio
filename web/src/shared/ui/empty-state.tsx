"use client";

import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * 空状态。
 * <p>
 * 强制要求给出下一步动作——旧实现里到处是 `<Empty description="暂无" />`，
 * 用户走到那里就没路了。
 */
export function EmptyState({
    icon,
    title,
    description,
    action,
    className,
}: {
    icon?: ReactNode;
    title: string;
    description?: string;
    action?: ReactNode;
    className?: string;
}) {
    return (
        <div
            className={cn(
                "flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--studio-line-strong)] px-6 py-12 text-center",
                className,
            )}
        >
            {icon ? <div className="mb-3 text-[var(--studio-faint)]">{icon}</div> : null}
            <div className="text-sm font-medium text-[var(--studio-ink)]">{title}</div>
            {description ? (
                <p className="mt-1.5 max-w-sm text-xs leading-5 text-[var(--studio-muted)]">{description}</p>
            ) : null}
            {action ? <div className="mt-4">{action}</div> : null}
        </div>
    );
}
