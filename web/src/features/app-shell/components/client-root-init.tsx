"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { useUserStore } from "@/features/auth/stores/use-user-store";

export function ClientRootInit({ children }: { children: ReactNode }) {
    const hydrateSession = useUserStore((state) => state.hydrateSession);

    useEffect(() => {
        hydrateSession();
    }, [hydrateSession]);

    return <>{children}</>;
}

