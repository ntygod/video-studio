"use client";

import type { HTMLAttributes } from "react";

import { cn } from "@/shared/lib/utils";

const PADDING_CLASS = {
    "0": "",
    "1": "p-[var(--sp-1)]",
    "2": "p-[var(--sp-2)]",
    "3": "p-[var(--sp-3)]",
    "4": "p-[var(--sp-4)]",
    "6": "p-[var(--sp-6)]",
} as const;

/**
 * 卡片：取代 16 处手抄的 `rounded-lg border border-line bg-surface`。
 * <p>
 * 默认 = panel + lift，不靠边框；media 模式让媒体出血到边缘；
 * 选中态只加左侧 2px 强调指示条，不改边框颜色。
 */
export function Card({
    interactive = false,
    selected = false,
    media = false,
    padding = "3",
    className,
    children,
    ...props
}: {
    interactive?: boolean;
    selected?: boolean;
    media?: boolean;
    padding?: keyof typeof PADDING_CLASS;
} & HTMLAttributes<HTMLDivElement>) {
    return (
        <div
            className={cn(
                "group relative overflow-hidden rounded-[var(--r-md)] bg-[var(--s-panel)] shadow-[var(--lift)]",
                "transition-[box-shadow,transform,background-color] duration-[var(--dur-base)] ease-[var(--ease-out)]",
                interactive && "cursor-pointer hover:shadow-[var(--s-shadow-md)]",
                PADDING_CLASS[media ? "0" : padding],
                className,
            )}
            {...props}
        >
            {selected ? (
                <span
                    aria-hidden
                    className="absolute inset-y-2 left-0 z-10 w-0.5 rounded-full bg-[var(--s-action)]"
                />
            ) : null}
            {children}
        </div>
    );
}
