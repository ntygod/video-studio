"use client";

import { create } from "zustand";

export type ServerUserRole = "user" | "admin";

export type ServerUserProfile = {
    id: number;
    email: string;
    username: string;
    nickname: string;
    avatar: string;
    role: ServerUserRole;
    status: number;
    creditBalance: number;
    createdAt: string;
    lastLoginAt: string;
    welcomeRead: boolean;
    passwordLockedUntil: string | null;
};

export type LocalUser = {
    id: string;
    username: string;
    displayName: string;
    avatarUrl: string;
    email: string;
    role: ServerUserRole;
    status: number;
    creditBalance: number;
    welcomeRead: boolean;
};

export type UserSession = {
    token: string;
    expiresAt: string;
    user: LocalUser;
};

const LOCAL_USER: LocalUser = {
    id: "local",
    username: "local",
    displayName: "本机创作者",
    avatarUrl: "",
    email: "local@video-studio.local",
    role: "user",
    status: 1,
    creditBalance: 999999,
    welcomeRead: true,
};

const LOCAL_SESSION: UserSession = {
    token: "local-session",
    expiresAt: "2099-12-31T00:00:00.000Z",
    user: LOCAL_USER,
};

type UserStore = {
    hydrated: boolean;
    token: string;
    expiresAt: string;
    user: LocalUser | null;
    hydrateSession: () => void;
    setSession: (session: { token: string; expiresAt: string; user: ServerUserProfile }) => void;
    setUser: (user: ServerUserProfile) => void;
    setCreditBalance: (creditBalance: number) => void;
    markWelcomeRead: () => void;
    clearSession: () => void;
    showAuthModal: boolean;
    pendingRedirect: string;
    openAuthModal: (redirect?: string) => void;
    closeAuthModal: () => void;
};

/** 本地单机模式：始终视为已登录的本机用户，无服务端会话。 */
export const useUserStore = create<UserStore>()((set) => ({
    hydrated: true,
    token: LOCAL_SESSION.token,
    expiresAt: LOCAL_SESSION.expiresAt,
    user: LOCAL_USER,
    showAuthModal: false,
    pendingRedirect: "",
    hydrateSession: () => {
        set({ hydrated: true, token: LOCAL_SESSION.token, expiresAt: LOCAL_SESSION.expiresAt, user: LOCAL_USER });
    },
    setSession: () => undefined,
    setUser: () => undefined,
    setCreditBalance: () => undefined,
    markWelcomeRead: () => undefined,
    clearSession: () => {
        set({ hydrated: true, token: LOCAL_SESSION.token, expiresAt: LOCAL_SESSION.expiresAt, user: LOCAL_USER });
    },
    openAuthModal: () => undefined,
    closeAuthModal: () => undefined,
}));

export function getAuthToken() {
    return LOCAL_SESSION.token;
}

