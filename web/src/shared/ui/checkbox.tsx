"use client";

import { Check } from "lucide-react";

import { cn } from "@/shared/lib/utils";

/**
 * 自绘勾选框：antd 的方框浮在媒体上太脏。
 * 选中态用中性 ink，不占用强调色配额。
 */
export function Checkbox({
    checked,
    onChange,
    label,
    disabled = false,
    className,
}: {
    checked: boolean;
    onChange?: (checked: boolean) => void;
    label?: string;
    disabled?: boolean;
    className?: string;
}) {
    return (
        <button
            type="button"
            role="checkbox"
            aria-checked={checked}
            aria-label={label}
            disabled={disabled}
            onClick={() => onChange?.(!checked)}
            className={cn(
                "inline-flex size-5 shrink-0 items-center justify-center rounded-[var(--r-xs)] border transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                checked
                    ? "border-[var(--s-ink)] bg-[var(--s-ink)] text-[var(--s-base)]"
                    : "border-[var(--hairline-strong)] bg-[var(--s-overlay)] text-transparent hover:border-[var(--s-action-line)]",
                disabled && "cursor-not-allowed opacity-50",
                className,
            )}
        >
            <Check className="size-3.5" strokeWidth={3} />
        </button>
    );
}
