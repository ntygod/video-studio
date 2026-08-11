"use client";

import type { ElementType, HTMLAttributes } from "react";

import { cn } from "@/shared/lib/utils";

export type TextVariant = "display" | "title" | "heading" | "body" | "label" | "caption" | "mono";
export type TextTone = "default" | "ink" | "muted" | "faint" | "danger" | "success" | "warning" | "info" | "accent";

const VARIANT_CLASS: Record<TextVariant, string> = {
    display: "font-display text-display font-semibold",
    title: "text-title font-semibold",
    heading: "text-heading font-semibold",
    body: "text-body",
    label: "text-label font-medium",
    caption: "text-caption font-medium",
    mono: "font-mono text-mono-sm font-[450] tabular-nums",
};

const TONE_CLASS: Record<TextTone, string> = {
    default: "text-[var(--s-text)]",
    ink: "text-[var(--s-ink)]",
    muted: "text-[var(--s-muted)]",
    faint: "text-[var(--s-faint)]",
    danger: "text-[var(--s-danger)]",
    success: "text-[var(--s-success)]",
    warning: "text-[var(--s-warning)]",
    info: "text-[var(--s-info)]",
    accent: "text-[var(--s-action)]",
};

const WEIGHT_CLASS = {
    400: "font-normal",
    450: "font-[450]",
    500: "font-medium",
    600: "font-semibold",
    700: "font-bold",
} as const;

/**
 * 文字基元：唯一允许控制字号/字重/色调的入口。
 */
export function Text({
    as: Tag = "span",
    variant = "body",
    tone = "default",
    weight,
    truncate = false,
    className,
    ...props
}: {
    as?: ElementType;
    variant?: TextVariant;
    tone?: TextTone;
    weight?: keyof typeof WEIGHT_CLASS;
    truncate?: boolean;
} & HTMLAttributes<HTMLElement>) {
    return (
        <Tag
            className={cn(
                VARIANT_CLASS[variant],
                TONE_CLASS[tone],
                weight && WEIGHT_CLASS[weight],
                truncate && "truncate",
                className,
            )}
            {...props}
        />
    );
}
