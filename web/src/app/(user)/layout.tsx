"use client";

import type { ReactNode } from "react";
import { AppShell } from "@/features/app-shell/components/app-shell";

export default function UserLayout({ children }: { children: ReactNode }) {
    return <AppShell>{children}</AppShell>;
}

