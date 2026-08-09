"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** 画布视图。P0 只搬运现有功能；board / timeline / versions 分别在 P2 / P4 加入。 */
export type CanvasView = "story" | "media" | "produce" | "brief";

/** 合法视图集合，用于校验来自 URL 的值。 */
export const CANVAS_VIEWS: readonly CanvasView[] = ["story", "media", "produce", "brief"] as const;

/** 默认视图。 */
export const DEFAULT_CANVAS_VIEW: CanvasView = "story";

/**
 * 把任意字符串收敛为合法视图。
 *
 * @param value string | undefined | null 来自路由的原始值
 * @return CanvasView 合法视图，非法时回落到默认视图
 */
export function normalizeCanvasView(value: string | undefined | null): CanvasView {
    return CANVAS_VIEWS.includes(value as CanvasView) ? (value as CanvasView) : DEFAULT_CANVAS_VIEW;
}

type PanelSizes = {
    /** 结构区宽度（px）。 */
    structure: number;
    /** Agent 区宽度（px）。 */
    agent: number;
};

const DEFAULT_PANEL_SIZES: PanelSizes = { structure: 260, agent: 400 };

/** 面板宽度的允许区间，拖拽与恢复时都会夹取。 */
const PANEL_LIMITS = {
    structure: { min: 200, max: 420 },
    agent: { min: 320, max: 640 },
} as const;

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

type WorkspaceStore = {
    /** 结构区是否折叠（仅桌面固定栏形态生效）。 */
    structureCollapsed: boolean;
    /** Agent 区是否折叠（仅桌面固定栏形态生效）。 */
    agentCollapsed: boolean;
    /** 窄屏下结构抽屉是否打开。 */
    structureDrawerOpen: boolean;
    /** 窄屏下助手抽屉是否打开。 */
    agentDrawerOpen: boolean;
    /** 任务坞是否展开。 */
    dockExpanded: boolean;
    /** 三栏宽度。 */
    panelSizes: PanelSizes;
    /** 按会话保存的输入框草稿，key 为 conversationId，切换对话时不丢内容。 */
    composerDrafts: Record<string, string>;

    toggleStructure: () => void;
    toggleAgent: () => void;
    setStructureDrawer: (open: boolean) => void;
    setAgentDrawer: (open: boolean) => void;
    toggleDock: () => void;
    setPanelSize: (panel: keyof PanelSizes, width: number) => void;
    setComposerDraft: (conversationId: string, draft: string) => void;
    clearComposerDraft: (conversationId: string) => void;
};

/**
 * 工作台的纯 UI 状态。
 * <p>
 * 这里只放"刷新后想恢复、但不属于服务端"的状态。项目、单元、稿件、素材等服务端数据
 * 一律走 React Query，不进本 store，避免出现两份真相。
 * <p>
 * 选中的单元与当前视图刻意不放这里——它们属于 URL（?unit= 与路由段），
 * 这样才能分享链接、前进后退和刷新恢复。
 */
export const useWorkspaceStore = create<WorkspaceStore>()(
    persist(
        (set) => ({
            structureCollapsed: false,
            agentCollapsed: false,
            structureDrawerOpen: false,
            agentDrawerOpen: false,
            dockExpanded: false,
            panelSizes: DEFAULT_PANEL_SIZES,
            composerDrafts: {},

            toggleStructure: () => set((state) => ({ structureCollapsed: !state.structureCollapsed })),
            toggleAgent: () => set((state) => ({ agentCollapsed: !state.agentCollapsed })),
            setStructureDrawer: (open) => set({ structureDrawerOpen: open }),
            setAgentDrawer: (open) => set({ agentDrawerOpen: open }),
            toggleDock: () => set((state) => ({ dockExpanded: !state.dockExpanded })),

            setPanelSize: (panel, width) =>
                set((state) => ({
                    panelSizes: {
                        ...state.panelSizes,
                        [panel]: clamp(width, PANEL_LIMITS[panel].min, PANEL_LIMITS[panel].max),
                    },
                })),

            setComposerDraft: (conversationId, draft) =>
                set((state) => ({ composerDrafts: { ...state.composerDrafts, [conversationId]: draft } })),

            clearComposerDraft: (conversationId) =>
                set((state) => {
                    const next = { ...state.composerDrafts };
                    delete next[conversationId];
                    return { composerDrafts: next };
                }),
        }),
        {
            name: "video-studio:workspace",
            // 服务端没有 localStorage，若在创建时就注水会让首帧与 SSR 输出不一致（面板宽度是内联样式）。
            // 改为挂载后由 WorkspaceShell 手动 rehydrate，首帧一律用默认值。
            skipHydration: true,
            // 草稿只保留在内存里：它属于当前编辑会话，跨页面恢复反而容易发出过期内容。
            partialize: (state) => ({
                structureCollapsed: state.structureCollapsed,
                agentCollapsed: state.agentCollapsed,
                dockExpanded: state.dockExpanded,
                panelSizes: state.panelSizes,
            }),
        },
    ),
);

export { PANEL_LIMITS };

/**
 * 尚未选中具体对话时草稿的暂存 key。
 * <p>
 * 其他界面（项目库的起始提示、设定页的"让 AI 帮我整理"）可以先把内容写进这个位置，
 * 助手面板挂载后会读到它。
 */
export const SCRATCH_DRAFT_KEY = "__scratch__";
