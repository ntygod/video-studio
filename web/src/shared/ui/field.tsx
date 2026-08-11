"use client";

import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";
import { Text } from "@/shared/ui/text";

/**
 * 表单字段：label / hint / error 一套带走。
 */
export function Field({
    label,
    htmlFor,
    hint,
    error,
    required = false,
    children,
    className,
}: {
    label?: string;
    htmlFor?: string;
    hint?: string;
    error?: string;
    required?: boolean;
    children: ReactNode;
    className?: string;
}) {
    return (
        <div className={cn("flex flex-col gap-[var(--sp-1)]", className)}>
            {label ? (
                <label htmlFor={htmlFor} className="flex items-baseline gap-1">
                    <Text as="span" variant="label" tone="ink">
                        {label}
                    </Text>
                    {required ? <Text as="span" variant="caption" tone="danger">*</Text> : null}
                </label>
            ) : null}
            {children}
            {error ? (
                <Text as="p" variant="caption" tone="danger">
                    {error}
                </Text>
            ) : hint ? (
                <Text as="p" variant="caption" tone="muted">
                    {hint}
                </Text>
            ) : null}
        </div>
    );
}
