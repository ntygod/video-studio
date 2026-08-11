"use client";

import type { ReactNode } from "react";

import { Button as AntdButton } from "antd";
import type { ButtonProps as AntdButtonProps } from "antd";

import { cn } from "@/shared/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "dashed";

/**
 * 按钮：antd 收编。primary = 强调色（一屏最多一个）；
 * secondary = raised 底 + hairline；ghost = 纯文字；danger = 危险主操作。
 */
export function Button({
    variant = "secondary",
    size = "md",
    className,
    children,
    ...props
}: {
    variant?: ButtonVariant;
    size?: "sm" | "md";
} & Omit<AntdButtonProps, "variant" | "type" | "size">) {
    return (
        <AntdButton
            type={
                variant === "primary" || variant === "danger"
                    ? "primary"
                    : variant === "ghost"
                      ? "text"
                      : variant === "dashed"
                        ? "dashed"
                        : "default"
            }
            danger={variant === "danger"}
            size={size === "sm" ? "small" : "middle"}
            className={cn(
                variant === "ghost" && "!text-[var(--s-muted)] hover:!text-[var(--s-ink)]",
                className,
            )}
            {...props}
        >
            {children}
        </AntdButton>
    );
}

/**
 * 图标按钮：强制 aria-label。
 */
export function IconButton({
    label,
    icon,
    onClick,
    active = false,
    size = "sm",
    disabled = false,
    type = "button",
    className,
}: {
    label: string;
    icon: ReactNode;
    onClick?: () => void;
    active?: boolean;
    size?: "sm" | "md";
    disabled?: boolean;
    type?: "button" | "submit";
    className?: string;
}) {
    return (
        <button
            type={type}
            aria-label={label}
            title={label}
            disabled={disabled}
            onClick={onClick}
            className={cn(
                "inline-flex shrink-0 items-center justify-center rounded-[var(--r-sm)] text-[var(--s-muted)]",
                "transition-colors duration-[var(--dur-base)] ease-[var(--ease-out)]",
                "hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)] focus-visible:outline-none",
                active && "bg-[var(--s-raised)] text-[var(--s-ink)]",
                size === "sm" ? "size-7" : "size-8",
                disabled && "cursor-not-allowed opacity-50 hover:bg-transparent hover:text-[var(--s-muted)]",
                className,
            )}
        >
            {icon}
        </button>
    );
}
