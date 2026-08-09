"use client";

import { useEffect, type ReactNode } from "react";
import { Drawer, Spin } from "antd";

import { AgentPanel } from "@/features/agent/components/agent-panel";
import { JobDock } from "@/features/jobs/components/job-dock";
import { StructurePanel } from "@/features/structure/components/structure-panel";
import { WorkspaceTopbar } from "@/features/workspace/components/workspace-topbar";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { useIsAgentInline, useIsStructureInline } from "@/shared/hooks/use-media-query";
import { ErrorPanel, PanelErrorBoundary } from "@/shared/ui/error-panel";
import { PanelResizer } from "@/shared/ui/panel-resizer";

/**
 * 工作台三栏骨架。
 * <p>
 * 结构区 · 画布 · Agent 区，底部常驻任务坞。左右两栏可拖拽调宽、可折叠，
 * 宽度与折叠状态持久化。工作台内不再挂全局导航栏——项目内的横向空间应该全部给创作。
 */
export function WorkspaceShell({ children }: { children: ReactNode }) {
    const { project, isLoading, error } = useWorkspaceData();

    const structureCollapsed = useWorkspaceStore((state) => state.structureCollapsed);
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const structureDrawerOpen = useWorkspaceStore((state) => state.structureDrawerOpen);
    const agentDrawerOpen = useWorkspaceStore((state) => state.agentDrawerOpen);
    const setStructureDrawer = useWorkspaceStore((state) => state.setStructureDrawer);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);
    const panelSizes = useWorkspaceStore((state) => state.panelSizes);
    const setPanelSize = useWorkspaceStore((state) => state.setPanelSize);
    const toggleStructure = useWorkspaceStore((state) => state.toggleStructure);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);

    const structureInline = useIsStructureInline();
    const agentInline = useIsAgentInline();

    // 面板宽度与折叠状态存在 localStorage，挂载后才注水，避免与 SSR 首帧不一致。
    useEffect(() => {
        void useWorkspaceStore.persist.rehydrate();
    }, []);

    // ⌘\ 折叠结构区，⌘J 折叠助手区；窄屏下改为开合抽屉。
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (!event.metaKey && !event.ctrlKey) return;
            if (event.key === "\\") {
                event.preventDefault();
                if (structureInline) toggleStructure();
                else setStructureDrawer(!structureDrawerOpen);
            } else if (event.key.toLowerCase() === "j") {
                event.preventDefault();
                if (agentInline) toggleAgent();
                else setAgentDrawer(!agentDrawerOpen);
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [
        agentDrawerOpen,
        agentInline,
        setAgentDrawer,
        setStructureDrawer,
        structureDrawerOpen,
        structureInline,
        toggleAgent,
        toggleStructure,
    ]);

    if (error) {
        return (
            <div className="flex h-dvh items-center justify-center">
                <ErrorPanel title="项目加载失败" message={error.message} onRetry={() => window.location.reload()} />
            </div>
        );
    }

    if (isLoading && !project) {
        return (
            <div className="flex h-dvh items-center justify-center">
                <Spin size="large" />
            </div>
        );
    }

    if (!project) {
        return (
            <div className="flex h-dvh items-center justify-center">
                <ErrorPanel title="项目不存在" message="它可能已被删除。" />
            </div>
        );
    }

    return (
        <div className="flex h-dvh flex-col overflow-hidden bg-[var(--studio-bg)]">
            <WorkspaceTopbar />

            <div className="flex min-h-0 flex-1">
                {!structureCollapsed ? (
                    <>
                        <aside
                            className="hidden shrink-0 lg:block"
                            style={{ width: panelSizes.structure }}
                            aria-label="项目结构"
                        >
                            <PanelErrorBoundary title="结构面板出错了">
                                <StructurePanel />
                            </PanelErrorBoundary>
                        </aside>
                        <div className="hidden lg:block">
                            <PanelResizer
                                side="left"
                                width={panelSizes.structure}
                                onResize={(width) => setPanelSize("structure", width)}
                                label="调整结构面板宽度"
                            />
                        </div>
                    </>
                ) : null}

                <main className="hide-scrollbar min-w-0 flex-1 overflow-y-auto bg-[var(--studio-bg)]">
                    <PanelErrorBoundary title="这个视图出错了">{children}</PanelErrorBoundary>
                </main>

                {!agentCollapsed ? (
                    <>
                        <div className="hidden xl:block">
                            <PanelResizer
                                side="right"
                                width={panelSizes.agent}
                                onResize={(width) => setPanelSize("agent", width)}
                                label="调整助手面板宽度"
                            />
                        </div>
                        <aside
                            className="hidden shrink-0 xl:block"
                            style={{ width: panelSizes.agent }}
                            aria-label="AI 创作助手"
                        >
                            <PanelErrorBoundary title="助手面板出错了">
                                <AgentPanel onCollapse={toggleAgent} />
                            </PanelErrorBoundary>
                        </aside>
                    </>
                ) : null}
            </div>

            <PanelErrorBoundary title="任务坞出错了">
                <JobDock />
            </PanelErrorBoundary>

            <Drawer
                title="项目结构"
                placement="left"
                width={300}
                open={!structureInline && structureDrawerOpen}
                onClose={() => setStructureDrawer(false)}
                styles={{ body: { padding: 0 } }}
            >
                <PanelErrorBoundary title="结构面板出错了">
                    <StructurePanel />
                </PanelErrorBoundary>
            </Drawer>

            <Drawer
                title="AI 创作助手"
                placement="right"
                width={420}
                open={!agentInline && agentDrawerOpen}
                onClose={() => setAgentDrawer(false)}
                styles={{ body: { padding: 0 } }}
            >
                <PanelErrorBoundary title="助手面板出错了">
                    <AgentPanel />
                </PanelErrorBoundary>
            </Drawer>
        </div>
    );
}
