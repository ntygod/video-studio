"use client";

import { Tooltip } from "antd";
import { Clapperboard } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useUserStore } from "@/features/auth/stores/use-user-store";
import { ThemePreferenceMenu } from "@/features/theme/components/theme-preference-menu";
import { navigationTools, type NavigationToolSlug } from "@/shared/constants/navigation-tools";
import { cn } from "@/shared/lib/utils";

export function AppSidebar() {
    const pathname = usePathname();
    const user = useUserStore((state) => state.user);
    const slug = pathname === "/" ? "home" : pathname.split("/").filter(Boolean)[0];
    const activeSlug = navigationTools.some((tool) => tool.slug === slug) ? (slug as NavigationToolSlug) : undefined;

    const renderNavItem = (tool: (typeof navigationTools)[number]) => {
        const Icon = tool.icon;
        const active = tool.slug === activeSlug;
        return (
            <Link
                key={tool.slug}
                href={tool.slug === "home" ? "/" : "/" + tool.slug}
                className={cn("sidebar-rail-item", active ? "sidebar-rail-item-active" : "sidebar-rail-item-inactive")}
                aria-current={active ? "page" : undefined}
                title={tool.label}
            >
                <span className="sidebar-rail-icon">
                    <Icon className="size-5" />
                </span>
                <span className="sidebar-rail-label">{tool.label}</span>
            </Link>
        );
    };

    return (
        <aside className="studio-sidebar-rail flex h-dvh w-[88px] shrink-0 flex-col">
            <div className="flex h-[72px] items-center justify-center border-b border-[var(--studio-line)]">
                <Tooltip title="Video Studio" placement="right">
                    <Link href="/" className="sidebar-brand-mark" aria-label="Video Studio 首页">
                        <span className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--studio-brand-start)] to-[var(--studio-brand-end)] text-white shadow-[var(--studio-shadow)]">
                            <Clapperboard className="size-5" />
                        </span>
                    </Link>
                </Tooltip>
            </div>

            <nav className="hide-scrollbar flex min-h-0 flex-1 flex-col items-center gap-1.5 overflow-y-auto px-2 pb-3">
                {navigationTools.map(renderNavItem)}
            </nav>

            <div className="flex flex-col items-center gap-2 border-t border-[var(--studio-line)] px-2 py-2">
                {user ? (
                    <div className="sidebar-user-dot" title={user.displayName}>
                        {(user.displayName || "V").charAt(0)}
                    </div>
                ) : null}
                <ThemePreferenceMenu />
            </div>
        </aside>
    );
}

