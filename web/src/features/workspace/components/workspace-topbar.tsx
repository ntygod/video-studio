"use client";

import { AudioLines, Clapperboard, Compass, FileText, History, Images, LayoutGrid, PanelLeft, PanelRight, Search, Settings } from "lucide-react";
import Link from "next/link";

import { ThemePreferenceMenu } from "@/features/theme/components/theme-preference-menu";
import { ApprovalCenter } from "@/features/workspace/components/approval-center";
import { FreshnessCenter } from "@/features/workspace/components/freshness-center";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { usePathname } from "next/navigation";

import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore, type CanvasView } from "@/features/workspace/stores/use-workspace-store";
import { useIsAgentInline, useIsStructureInline } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";
import { Button, Surface, Tooltip } from "@/shared/ui";

type ViewTab = {
    view: CanvasView;
    label: string;
    icon: typeof FileText;
};

/**
 * 画布视图。
 * <p>
 * P0 只是把原来的四个 antd Tab 搬到路由上；分镜（board）与时间线（timeline）
 * 分别在 P2 / P4 加入。
 */
const VIEW_TABS: ViewTab[] = [
    { view: "brief", label: "策划", icon: Compass },
    { view: "story", label: "稿件", icon: FileText },
    { view: "board", label: "分镜", icon: LayoutGrid },
    { view: "media", label: "素材", icon: Images },
];

/** 工作台顶栏：面包屑 + 视图切换 + 全局动作。 */
export function WorkspaceTopbar() {
    const pathname = usePathname();
    const { projectId, view, hrefFor, selectedUnitId, setSelectedUnit } = useWorkspaceRoute();
    const { project, selectedUnit } = useWorkspaceData();

    const structureCollapsed = useWorkspaceStore((state) => state.structureCollapsed);
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const toggleStructure = useWorkspaceStore((state) => state.toggleStructure);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setStructureDrawer = useWorkspaceStore((state) => state.setStructureDrawer);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);
    const setCommandPalette = useWorkspaceStore((state) => state.setCommandPalette);

    // 窄屏下两侧是抽屉，按钮改为打开抽屉而不是切换折叠。
    const structureInline = useIsStructureInline();
    const agentInline = useIsAgentInline();

    const structureHidden = structureInline ? structureCollapsed : true;
    const agentHidden = agentInline ? agentCollapsed : true;

    return (
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--hairline)] bg-[var(--s-panel)] px-2.5">
            <Tooltip title={structureHidden ? "展开结构（⌘\\）" : "收起结构（⌘\\）"}>
                <Button
                    size="sm"
                    variant="ghost"
                    aria-label={structureHidden ? "展开结构面板" : "收起结构面板"}
                    aria-pressed={!structureHidden}
                    icon={<PanelLeft className="size-4" />}
                    onClick={() => (structureInline ? toggleStructure() : setStructureDrawer(true))}
                />
            </Tooltip>

            <nav aria-label="位置" className="flex min-w-0 items-center gap-1.5 text-label">
                <button
                    type="button"
                    onClick={() => setSelectedUnit(null)}
                    className={cn(
                        "max-w-[180px] truncate transition-colors",
                        selectedUnitId ? "text-[var(--s-muted)] hover:text-[var(--s-ink)]" : "text-[var(--s-ink)]",
                    )}
                >
                    {project?.title || "…"}
                </button>
                {selectedUnit ? (
                    <>
                        <span className="text-[var(--s-faint)]">›</span>
                        <span className="max-w-[220px] truncate text-[var(--s-ink)]">{selectedUnit.title}</span>
                    </>
                ) : null}
            </nav>

            <div className="flex min-w-0 flex-1 justify-center px-1">
                <Surface
                    level="raised"
                    radius="sm"
                    className="hide-scrollbar flex min-w-0 max-w-full items-center gap-0.5 overflow-x-auto p-0.5"
                >
                    <div role="tablist" aria-label="画布视图" className="flex items-center gap-0.5">
                        {VIEW_TABS.map((tab) => {
                            const Icon = tab.icon;
                            const active =
                                tab.view === view && !pathname.endsWith("/timeline") && !pathname.endsWith("/versions");
                            return (
                                <Link
                                    key={tab.view}
                                    href={hrefFor(tab.view)}
                                    role="tab"
                                    aria-selected={active}
                                    aria-label={tab.label}
                                    className={cn(
                                        "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[var(--r-sm)] px-2.5 py-1 text-label transition-colors",
                                        active
                                            ? "bg-[var(--s-panel)] text-[var(--s-ink)] shadow-[var(--s-shadow-sm)]"
                                            : "text-[var(--s-muted)] hover:text-[var(--s-ink)]",
                                    )}
                                >
                                    <Icon className="size-3.5" />
                                    <span className="hidden xl:inline">{tab.label}</span>
                                </Link>
                            );
                        })}
                        <Link
                            href={`/projects/${encodeURIComponent(projectId)}/timeline`}
                            aria-label="时间线"
                            className={cn(
                                "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[var(--r-sm)] px-2.5 py-1 text-label transition-colors",
                                pathname.endsWith("/timeline")
                                    ? "bg-[var(--s-panel)] text-[var(--s-ink)] shadow-[var(--s-shadow-sm)]"
                                    : "text-[var(--s-muted)] hover:text-[var(--s-ink)]",
                            )}
                        >
                            <AudioLines className="size-3.5" />
                            <span className="hidden xl:inline">时间线</span>
                        </Link>
                        <Link
                            href={hrefFor("produce")}
                            aria-label="交付"
                            className={cn(
                                "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[var(--r-sm)] px-2.5 py-1 text-label transition-colors",
                                view === "produce" && !pathname.endsWith("/timeline") && !pathname.endsWith("/versions")
                                    ? "bg-[var(--s-panel)] text-[var(--s-ink)] shadow-[var(--s-shadow-sm)]"
                                    : "text-[var(--s-muted)] hover:text-[var(--s-ink)]",
                            )}
                        >
                            <Clapperboard className="size-3.5" />
                            <span className="hidden xl:inline">交付</span>
                        </Link>
                        <Link
                            href={`/projects/${encodeURIComponent(projectId)}/versions`}
                            aria-label="版本"
                            className={cn(
                                "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[var(--r-sm)] px-2.5 py-1 text-label transition-colors",
                                pathname.endsWith("/versions")
                                    ? "bg-[var(--s-panel)] text-[var(--s-ink)] shadow-[var(--s-shadow-sm)]"
                                    : "text-[var(--s-muted)] hover:text-[var(--s-ink)]",
                            )}
                        >
                            <History className="size-3.5" />
                            <span className="hidden 2xl:inline">版本</span>
                        </Link>
                    </div>
                </Surface>
            </div>

            <div className="flex shrink-0 items-center gap-1">
                <ApprovalCenter projectId={projectId} />
                <FreshnessCenter projectId={projectId} />
                <Tooltip title="命令面板（⌘K）">
                    <Button
                        size="sm"
                        variant="ghost"
                        aria-label="打开命令面板"
                        icon={<Search className="size-4" />}
                        onClick={() => setCommandPalette(true)}
                    />
                </Tooltip>
                <ThemePreferenceMenu variant="toolbar" />
                <Tooltip title="模型设置">
                    <Link href="/settings" aria-label="模型设置">
                        <Button size="sm" variant="ghost" icon={<Settings className="size-4" />} />
                    </Link>
                </Tooltip>
                <Tooltip title={agentHidden ? "展开助手（⌘J）" : "收起助手（⌘J）"}>
                    <Button
                        size="sm"
                        variant="ghost"
                        aria-label={agentHidden ? "展开 AI 助手" : "收起 AI 助手"}
                        aria-pressed={!agentHidden}
                        icon={<PanelRight className="size-4" />}
                        onClick={() => (agentInline ? toggleAgent() : setAgentDrawer(true))}
                    />
                </Tooltip>
            </div>
        </header>
    );
}
