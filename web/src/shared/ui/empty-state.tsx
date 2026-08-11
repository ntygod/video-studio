"use client";

import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * 空状态：起点，不是占位符。无虚线框；display 标题 + 唯一主按钮。
 */
export function EmptyState({
    icon,
    title,
    description,
    action,
    secondaryAction,
    className,
}: {
    icon?: ReactNode;
    title: string;
    description?: string;
    action?: ReactNode;
    secondaryAction?: ReactNode;
    className?: string;
}) {
    return (
        <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
            {icon ? (
                <div className="mb-4 flex size-12 items-center justify-center rounded-[var(--r-md)] bg-[var(--s-raised)] text-[var(--s-muted)]">
                    {icon}
                </div>
            ) : null}
            <h3 className="font-display text-display font-semibold text-[var(--s-ink)]">{title}</h3>
            {description ? (
                <p className="mt-2 max-w-sm text-body leading-[1.65] text-[var(--s-muted)]">{description}</p>
            ) : null}
            {action ? <div className="mt-6">{action}</div> : null}
            {secondaryAction ? <div className="mt-2">{secondaryAction}</div> : null}
        </div>
    );
}
