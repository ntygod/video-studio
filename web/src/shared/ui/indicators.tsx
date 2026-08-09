"use client";

import { cn } from "@/shared/lib/utils";

/** 三段完成度：稿件 / 素材 / 成片。 */
export type CompletionTriple = [boolean, boolean, boolean];

/**
 * 单元完成度指示：三个小圆点分别代表稿件、素材、成片。
 * <p>
 * 长篇创作里一眼看出每个单元卡在哪一环，比一个笼统的百分比有用得多。
 */
export function CompletionDots({ value, className }: { value: CompletionTriple; className?: string }) {
    const labels = ["稿件", "素材", "成片"];
    return (
        <span className={cn("inline-flex items-center gap-[3px]", className)} title={
            labels.map((label, index) => `${label}${value[index] ? "✓" : "—"}`).join(" · ")
        }>
            {value.map((done, index) => (
                <span
                    key={labels[index]}
                    className={cn(
                        "block size-[5px] rounded-full",
                        done ? "bg-[var(--studio-action)]" : "bg-[var(--studio-line-strong)]",
                    )}
                />
            ))}
        </span>
    );
}

/**
 * 环形进度。
 *
 * @param value number 0~1 的完成比例
 * @param size number 直径（px）
 */
export function ProgressRing({ value, size = 28, className }: { value: number; size?: number; className?: string }) {
    const ratio = Math.max(0, Math.min(1, value));
    const stroke = 3;
    const radius = (size - stroke) / 2;
    const circumference = 2 * Math.PI * radius;

    return (
        <span className={cn("relative inline-flex items-center justify-center", className)} style={{ width: size, height: size }}>
            <svg width={size} height={size} className="-rotate-90">
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    className="stroke-[var(--studio-line-strong)]"
                />
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={circumference * (1 - ratio)}
                    className="stroke-[var(--studio-action)] transition-[stroke-dashoffset] duration-300"
                />
            </svg>
            <span className="absolute text-[9px] font-medium tabular-nums text-[var(--studio-muted)]">
                {Math.round(ratio * 100)}
            </span>
        </span>
    );
}

/** 状态圆点，用于任务与版本状态。 */
export function StatusDot({ tone, pulse }: { tone: "idle" | "active" | "success" | "error" | "warning"; pulse?: boolean }) {
    const toneClass = {
        idle: "bg-[var(--studio-line-strong)]",
        active: "bg-[var(--studio-info)]",
        success: "bg-[var(--studio-success)]",
        error: "bg-[var(--studio-danger)]",
        warning: "bg-[var(--studio-warning)]",
    }[tone];

    return (
        <span className="relative inline-flex size-2 shrink-0">
            {pulse ? <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", toneClass)} /> : null}
            <span className={cn("relative inline-flex size-2 rounded-full", toneClass)} />
        </span>
    );
}
