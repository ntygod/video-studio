"use client";

import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";

import { AppSidebar } from "@/features/app-shell/components/app-sidebar";
import { MobileNavDrawer } from "@/features/app-shell/components/mobile-nav-drawer";
import { navigationTools, type NavigationToolSlug } from "@/shared/constants/navigation-tools";

export function AppShell({ children }: { children: ReactNode }) {
    const pathname = usePathname();
    const [mobileNavOpen, setMobileNavOpen] = useState(false);

    const slug = pathname === "/" ? "home" : pathname.split("/").filter(Boolean)[0];
    const activeToolSlug = navigationTools.some((tool) => tool.slug === slug) ? (slug as NavigationToolSlug) : undefined;

    return (
        <div className="studio-shell-bg relative flex h-dvh overflow-hidden">
            <div className="hidden md:block">
                <AppSidebar />
            </div>
            <button
                type="button"
                className="fixed left-3 top-3 z-30 inline-flex size-9 items-center justify-center rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] text-[var(--studio-muted)] transition-colors hover:text-[var(--studio-ink)] md:hidden"
                onClick={() => setMobileNavOpen(true)}
                aria-label="打开导航菜单"
            >
                <Menu className="size-4" />
            </button>
            <MobileNavDrawer open={mobileNavOpen} activeToolSlug={activeToolSlug} onClose={() => setMobileNavOpen(false)} />

            <div className="relative z-10 flex min-w-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-y-auto pt-12 md:pt-0">{children}</div>
            </div>
        </div>
    );
}

