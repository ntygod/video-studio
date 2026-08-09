"use client";

import type { MenuProps } from "antd";
import { Dropdown } from "antd";
import { Check, SunMoon } from "lucide-react";

import { useThemeStore } from "@/features/theme/stores/use-theme-store";
import { cn } from "@/shared/lib/utils";
import type { ThemePreference } from "@/shared/lib/theme-preference";

type ThemePreferenceMenuProps = {
    /** icon 用于侧栏底部（菜单向上弹出），toolbar 用于顶栏（菜单向下弹出），drawer 用于移动端抽屉。 */
    variant?: "icon" | "toolbar" | "drawer";
    className?: string;
    onAfterSelect?: () => void;
};

const THEME_LABELS: Record<ThemePreference, string> = {
    system: "跟随系统",
    light: "浅色模式",
    dark: "暗色模式",
};

const RESOLVED_THEME_LABELS = {
    light: "浅色",
    dark: "暗色",
} as const;

/**
 * 全局主题偏好切换菜单。
 *
 * @param props ThemePreferenceMenuProps 渲染形态与回调
 * @return JSX.Element
 */
export function ThemePreferenceMenu({ variant = "icon", className, onAfterSelect }: ThemePreferenceMenuProps) {
    const preference = useThemeStore((state) => state.preference);
    const resolvedTheme = useThemeStore((state) => state.resolvedTheme);
    const setThemePreference = useThemeStore((state) => state.setThemePreference);

    const items: MenuProps["items"] = (["system", "light", "dark"] as ThemePreference[]).map((item) => ({
        key: item,
        icon: preference === item ? <Check className="size-4" /> : <span className="block size-4" aria-hidden="true" />,
        label: (
            <div className="flex min-w-40 items-center justify-between gap-3">
                <span>{THEME_LABELS[item]}</span>
                {item === "system" ? <span className="text-xs text-[var(--studio-faint)]">当前：{RESOLVED_THEME_LABELS[resolvedTheme]}</span> : null}
            </div>
        ),
    }));

    return (
        <Dropdown
            trigger={["click"]}
            placement={variant === "icon" ? "topLeft" : "bottomRight"}
            arrow={false}
            menu={{
                items,
                onClick: ({ key }) => {
                    setThemePreference(key as ThemePreference);
                    onAfterSelect?.();
                },
            }}
        >
            {variant === "drawer" ? (
                <button
                    type="button"
                    className={cn(
                        "flex w-full items-center justify-between gap-3 rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] px-3 py-3 text-left transition-colors hover:bg-[var(--studio-surface-hover)]",
                        className,
                    )}
                    aria-label="切换主题"
                    title="切换主题"
                >
                    <span className="flex items-center gap-3">
                        <span className="inline-flex size-9 items-center justify-center rounded-lg bg-[var(--studio-action-soft)] text-[var(--studio-ink)]">
                            <SunMoon className="size-4.5" />
                        </span>
                        <span>
                            <span className="block text-sm font-medium text-[var(--studio-ink)]">主题模式</span>
                            <span className="block text-xs text-[var(--studio-faint)]">
                                {preference === "system" ? `跟随系统 · 当前${RESOLVED_THEME_LABELS[resolvedTheme]}` : THEME_LABELS[preference]}
                            </span>
                        </span>
                    </span>
                    <span className="text-xs text-[var(--studio-muted)]">切换</span>
                </button>
            ) : variant === "toolbar" ? (
                <button
                    type="button"
                    className={cn(
                        "inline-flex size-7 items-center justify-center rounded-md text-[var(--studio-muted)] transition-colors hover:bg-[var(--studio-surface-hover)] hover:text-[var(--studio-ink)]",
                        className,
                    )}
                    aria-label="切换主题"
                    title="切换主题"
                >
                    <SunMoon className="size-4" />
                </button>
            ) : (
                <button type="button" className={cn("sidebar-rail-action", className)} aria-label="切换主题" title="切换主题">
                    <SunMoon className="size-4.5" />
                </button>
            )}
        </Dropdown>
    );
}
