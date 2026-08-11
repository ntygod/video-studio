"use client";

import { cn } from "@/shared/lib/utils";

/** 三段完成度：稿件 / 素材 / 成片。 */
export type CompletionTriple = [boolean, boolean, boolean];

/**
 * 单元完成度指示：三个小圆点分别代表稿件、素材、成片。
 * 强调色不用于此处——完成 = 中性 ink，未完成 = hairline。
 */
export function CompletionDots({ value, className }: { value: CompletionTriple; className?: string }) {
    const labels = ["稿件", "素材", "成片"];
    return (
        <span
            className={cn("inline-flex items-center gap-[3px]", className)}
            title={labels.map((label, index) => `${label}${value[index] ? "✓" : "—"}`).join(" · ")}
        >
            {value.map((done, index) => (
                <span
                    key={labels[index]}
                    className={cn(
                        "block size-[5px] rounded-full",
                        done ? "bg-[var(--s-ink)]" : "bg-[var(--hairline-strong)]",
                    )}
                />
            ))}
        </span>
    );
}

/**
 * 环形进度：生成中的进度指示，中性色，不盖蒙层。
 *
 * @param value number 0~1 的完成比例
 * @param indeterminate boolean 进度未知时转圈，不显示假百分比
 * @param size number 直径（px）
 */
export function ProgressRing({
    value,
    size = 28,
    indeterminate = false,
    className,
}: {
    value?: number;
    size?: number;
    indeterminate?: boolean;
    className?: string;
}) {
    const ratio = Math.max(0, Math.min(1, value ?? 0));
    const stroke = 3;
    const radius = (size - stroke) / 2;
    const circumference = 2 * Math.PI * radius;

    return (
        <span className={cn("relative inline-flex items-center justify-center", className)} style={{ width: size, height: size }}>
            <svg width={size} height={size} className={cn("-rotate-90", indeterminate && "animate-spin")}>
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    className="stroke-[var(--hairline-strong)]"
                />
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    strokeLinecap="round"
                    strokeDasharray={indeterminate ? `${circumference * 0.25} ${circumference}` : circumference}
                    strokeDashoffset={indeterminate ? 0 : circumference * (1 - ratio)}
                    className={cn(
                        "stroke-[var(--s-ink)]",
                        !indeterminate && "transition-[stroke-dashoffset] duration-300",
                    )}
                />
            </svg>
            {/* 进度未知时不显示百分比——假的 35% 比没有数字更糟 */}
            {indeterminate ? null : (
                <span className="absolute font-mono text-caption font-[450] tabular-nums text-[var(--s-muted)]">
                    {Math.round(ratio * 100)}
                </span>
            )}
        </span>
    );
}

/** 状态圆点：用于任务与版本状态，pulse 走 s-pop 动效。 */
export function StatusDot({ tone, pulse }: { tone: "idle" | "active" | "success" | "error" | "warning"; pulse?: boolean }) {
    const toneClass = {
        idle: "bg-[var(--hairline-strong)]",
        active: "bg-[var(--s-info)]",
        success: "bg-[var(--s-success)]",
        error: "bg-[var(--s-danger)]",
        warning: "bg-[var(--s-warning)]",
    }[tone];

    return (
        <span className="relative inline-flex size-2 shrink-0">
            {pulse ? (
                <span className={cn("absolute inline-flex size-full rounded-full opacity-40", toneClass, "animate-s-pop")} />
            ) : null}
            <span className={cn("relative inline-flex size-2 rounded-full", toneClass)} />
        </span>
    );
}
