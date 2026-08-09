"use client";

import { Button, Tooltip } from "antd";
import { BookMarked, Clapperboard, FileText, Images, PanelLeft, PanelRight, Settings } from "lucide-react";
import Link from "next/link";

import { ThemePreferenceMenu } from "@/features/theme/components/theme-preference-menu";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore, type CanvasView } from "@/features/workspace/stores/use-workspace-store";
import { useIsAgentInline, useIsStructureInline } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";

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
    { view: "story", label: "故事", icon: FileText },
    { view: "media", label: "素材", icon: Images },
    { view: "produce", label: "成片", icon: Clapperboard },
    { view: "brief", label: "设定", icon: BookMarked },
];

/** 工作台顶栏：面包屑 + 视图切换 + 全局动作。 */
export function WorkspaceTopbar() {
    const { view, hrefFor, selectedUnitId, setSelectedUnit } = useWorkspaceRoute();
    const { project, selectedUnit } = useWorkspaceData();

    const structureCollapsed = useWorkspaceStore((state) => state.structureCollapsed);
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const toggleStructure = useWorkspaceStore((state) => state.toggleStructure);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setStructureDrawer = useWorkspaceStore((state) => state.setStructureDrawer);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);

    // 窄屏下两侧是抽屉，按钮改为打开抽屉而不是切换折叠。
    const structureInline = useIsStructureInline();
    const agentInline = useIsAgentInline();

    const structureHidden = structureInline ? structureCollapsed : true;
    const agentHidden = agentInline ? agentCollapsed : true;

    return (
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[var(--studio-line)] bg-[var(--studio-surface)] px-2">
            <Tooltip title={structureHidden ? "展开结构（⌘\\）" : "收起结构（⌘\\）"}>
                <Button
                    size="small"
                    type="text"
                    aria-label={structureHidden ? "展开结构面板" : "收起结构面板"}
                    aria-pressed={!structureHidden}
                    icon={<PanelLeft className="size-4" />}
                    onClick={() => (structureInline ? toggleStructure() : setStructureDrawer(true))}
                />
            </Tooltip>

            <nav aria-label="位置" className="flex min-w-0 items-center gap-1.5 text-[12px]">
                <button
                    type="button"
                    onClick={() => setSelectedUnit(null)}
                    className={cn(
                        "max-w-[180px] truncate transition-colors",
                        selectedUnitId ? "text-[var(--studio-muted)] hover:text-[var(--studio-ink)]" : "text-[var(--studio-ink)]",
                    )}
                >
                    {project?.title || "…"}
                </button>
                {selectedUnit ? (
                    <>
                        <span className="text-[var(--studio-faint)]">›</span>
                        <span className="max-w-[220px] truncate text-[var(--studio-ink)]">{selectedUnit.title}</span>
                    </>
                ) : null}
            </nav>

            <div className="flex flex-1 justify-center">
                <div
                    role="tablist"
                    aria-label="画布视图"
                    className="flex items-center gap-0.5 rounded-lg bg-[var(--studio-surface-raised)] p-0.5"
                >
                    {VIEW_TABS.map((tab) => {
                        const Icon = tab.icon;
                        const active = tab.view === view;
                        return (
                            <Link
                                key={tab.view}
                                href={hrefFor(tab.view)}
                                role="tab"
                                aria-selected={active}
                                className={cn(
                                    "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition-colors",
                                    active
                                        ? "bg-[var(--studio-surface)] text-[var(--studio-ink)] shadow-[var(--studio-shadow-sm)]"
                                        : "text-[var(--studio-muted)] hover:text-[var(--studio-ink)]",
                                )}
                            >
                                <Icon className="size-3.5" />
                                {tab.label}
                            </Link>
                        );
                    })}
                </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
                <ThemePreferenceMenu variant="toolbar" />
                <Tooltip title="模型设置">
                    <Link href="/settings" aria-label="模型设置">
                        <Button size="small" type="text" icon={<Settings className="size-4" />} />
                    </Link>
                </Tooltip>
                <Tooltip title={agentHidden ? "展开助手（⌘J）" : "收起助手（⌘J）"}>
                    <Button
                        size="small"
                        type="text"
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
