"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useUserStore } from "@/features/auth/stores/use-user-store";
import { ThemePreferenceMenu } from "@/features/theme/components/theme-preference-menu";
import { navigationTools, type NavigationToolSlug } from "@/shared/constants/navigation-tools";
import { cn } from "@/shared/lib/utils";
import { Tooltip } from "@/shared/ui";

export function AppSidebar() {
    const pathname = usePathname();
    const user = useUserStore((state) => state.user);
    const slug = pathname === "/" || pathname.startsWith("/projects/") ? "home" : pathname.split("/").filter(Boolean)[0];
    const activeSlug = navigationTools.some((tool) => tool.slug === slug) ? (slug as NavigationToolSlug) : undefined;

    const renderNavItem = (tool: (typeof navigationTools)[number]) => {
        const Icon = tool.icon;
        const active = tool.slug === activeSlug;
        return (
            <Tooltip key={tool.slug} title={tool.label} placement="right">
                <Link
                    href={tool.slug === "home" ? "/" : "/" + tool.slug}
                    className={cn("sidebar-rail-item", active ? "sidebar-rail-item-active" : "sidebar-rail-item-inactive")}
                    aria-current={active ? "page" : undefined}
                >
                    <span className="sidebar-rail-icon">
                        <Icon className="size-4" />
                    </span>
                    <span className="sidebar-rail-label">{tool.label}</span>
                </Link>
            </Tooltip>
        );
    };

    return (
        <aside className="studio-sidebar-rail flex h-dvh w-14 shrink-0 flex-col">
            <div className="flex h-14 items-center justify-center border-b border-[var(--hairline)]">
                <Tooltip title="Video Studio" placement="right">
                    <Link href="/" className="sidebar-brand-mark" aria-label="Video Studio 首页">
                        <span className="flex size-8 items-center justify-center rounded-[10px] bg-[var(--s-ink)] text-label font-semibold text-[var(--s-base)]">
                            VS
                        </span>
                    </Link>
                </Tooltip>
            </div>

            <nav className="hide-scrollbar flex min-h-0 flex-1 flex-col items-center gap-1.5 overflow-y-auto px-2 py-3">
                {navigationTools.map(renderNavItem)}
            </nav>

            <div className="flex flex-col items-center gap-2 border-t border-[var(--hairline)] px-2 py-2">
                {user ? (
                    <div className="sidebar-user-dot !size-8 !rounded-full" title={user.displayName}>
                        {(user.displayName || "V").charAt(0)}
                    </div>
                ) : null}
                <ThemePreferenceMenu />
            </div>
        </aside>
    );
}
