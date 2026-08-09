import { FolderKanban, ListChecks, Settings } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavigationTool = {
    slug: string;
    label: string;
    icon: LucideIcon;
    group: "create" | "production" | "settings";
};

export const navigationTools = [
    { slug: "home", label: "项目", icon: FolderKanban, group: "create" },
    { slug: "jobs", label: "任务", icon: ListChecks, group: "production" },
    { slug: "settings", label: "模型", icon: Settings, group: "settings" },
] as const satisfies readonly NavigationTool[];

export type NavigationToolSlug = (typeof navigationTools)[number]["slug"];

export const NAV_GROUPS = [
    { key: "create", label: "创作" },
    { key: "production", label: "生产" },
    { key: "settings", label: "设置" },
] as const;
