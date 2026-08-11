"use client";

import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";

import { AppSidebar } from "@/features/app-shell/components/app-sidebar";
import { MobileNavDrawer } from "@/features/app-shell/components/mobile-nav-drawer";
import { navigationTools, type NavigationToolSlug } from "@/shared/constants/navigation-tools";
import { IconButton } from "@/shared/ui";

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
            <IconButton
                label="打开导航菜单"
                icon={<Menu className="size-4" />}
                size="md"
                onClick={() => setMobileNavOpen(true)}
                className="fixed left-3 top-3 z-30 bg-[var(--s-panel)] shadow-[var(--s-shadow-md)] md:hidden"
            />
            <MobileNavDrawer open={mobileNavOpen} activeToolSlug={activeToolSlug} onClose={() => setMobileNavOpen(false)} />

            <div className="relative z-10 flex min-w-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-y-auto pt-12 md:pt-0">{children}</div>
            </div>
        </div>
    );
}
