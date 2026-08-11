"use client";

import Link from "next/link";

import { ThemePreferenceMenu } from "@/features/theme/components/theme-preference-menu";
import { NAV_GROUPS, navigationTools, type NavigationToolSlug } from "@/shared/constants/navigation-tools";
import { cn } from "@/shared/lib/utils";
import { Drawer, Text } from "@/shared/ui";

type MobileNavDrawerProps = {
    open: boolean;
    activeToolSlug?: NavigationToolSlug;
    onClose: () => void;
};

export function MobileNavDrawer({ open, activeToolSlug, onClose }: MobileNavDrawerProps) {
    return (
        <Drawer title="创作导航" placement="left" size={292} open={open} onClose={onClose} className="md:hidden">
            <div className="space-y-5">
                {NAV_GROUPS.map((group) => {
                    const tools = navigationTools.filter((tool) => tool.group === group.key);
                    if (!tools.length) return null;
                    return (
                        <section key={group.key}>
                            <Text variant="label" tone="faint" className="mb-2 px-1">
                                {group.label}
                            </Text>
                            <div className="grid grid-cols-2 gap-2">
                                {tools.map((tool) => {
                                    const Icon = tool.icon;
                                    const active = tool.slug === activeToolSlug;
                                    return (
                                        <Link
                                            key={tool.slug}
                                            href={tool.slug === "home" ? "/" : "/" + tool.slug}
                                            onClick={onClose}
                                            className={cn(
                                                "relative flex min-h-20 flex-col justify-between rounded-[var(--r-md)] p-3 transition-colors",
                                                active
                                                    ? "bg-[var(--s-raised)] font-medium text-[var(--s-ink)]"
                                                    : "border-[var(--hairline)] bg-[var(--s-raised)] text-[var(--s-muted)] hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)]",
                                            )}
                                        >
                                            {active ? (
                                                <span
                                                    aria-hidden
                                                    className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-action)]"
                                                />
                                            ) : null}
                                            <Icon className="size-5" />
                                            <Text variant="body">{tool.label}</Text>
                                        </Link>
                                    );
                                })}
                            </div>
                        </section>
                    );
                })}
                <section className="border-t border-[var(--hairline)] pt-5">
                    <Text variant="label" tone="faint" className="mb-2 px-1">
                        界面主题
                    </Text>
                    <ThemePreferenceMenu variant="drawer" onAfterSelect={onClose} />
                </section>
            </div>
        </Drawer>
    );
}
