"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { BookMarked, Clapperboard, FileText, FolderPlus, History, Images, LayoutGrid, PanelLeft, PanelRight, Search, Settings, Timer, UnfoldVertical } from "lucide-react";
import { useRouter } from "next/navigation";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore, type CanvasView } from "@/features/workspace/stores/use-workspace-store";
import { useIsAgentInline, useIsStructureInline } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";
import { useSearch } from "@/services/queries";
import { Input, Modal } from "@/shared/ui";

const VIEW_ICONS: Record<string, ReactNode> = {
    story: <FileText className="size-3.5" />,
    board: <LayoutGrid className="size-3.5" />,
    media: <Images className="size-3.5" />,
    produce: <Clapperboard className="size-3.5" />,
    brief: <BookMarked className="size-3.5" />,
    timeline: <Timer className="size-3.5" />,
    versions: <History className="size-3.5" />,
};

const VIEW_LABELS: Record<string, string> = {
    story: "稿件",
    board: "分镜",
    media: "素材",
    produce: "交付",
    brief: "策划",
    timeline: "时间线",
    versions: "版本",
};

const PALETTE_VIEWS = ["brief", "story", "board", "media", "timeline", "produce", "versions"] as const;

const SECTIONS = ["跳转视图", "搜索", "跳转单元", "操作"] as const;

type PaletteItem = {
    key: string;
    section: string;
    label: string;
    hint?: string;
    keywords: string;
    icon: ReactNode;
    run: () => void;
};

/**
 * ⌘K 命令面板（T5.1）：跳视图 / 跳单元 / FTS 搜索 / 执行动作。
 * <p>
 * 全局快捷键 ⌘K / Ctrl+K 打开；Esc / 点击遮罩关闭；方向键与 Enter 行走列表。
 */
export function CommandPalette() {
    const router = useRouter();
    const { projectId, selectedUnitId, setView, setSelectedUnit } = useWorkspaceRoute();
    const { unitOptions } = useWorkspaceData();

    const [query, setQuery] = useState("");
    const [activeIndex, setActiveIndex] = useState(0);
    const searchQuery = useSearch(projectId, query);

    const open = useWorkspaceStore((state) => state.commandPaletteOpen);
    const setOpen = useWorkspaceStore((state) => state.setCommandPalette);
    const requestUnitCreate = useWorkspaceStore((state) => state.requestUnitCreate);
    const toggleStructure = useWorkspaceStore((state) => state.toggleStructure);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setStructureDrawer = useWorkspaceStore((state) => state.setStructureDrawer);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);
    const toggleDock = useWorkspaceStore((state) => state.toggleDock);

    const structureInline = useIsStructureInline();
    const agentInline = useIsAgentInline();

    // 全局 ⌘K / Ctrl+K。
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                setOpen(!useWorkspaceStore.getState().commandPaletteOpen);
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [setOpen]);

    // 打开时重置查询并聚焦输入框。
    useEffect(() => {
        if (!open) return;
        setQuery("");
        setActiveIndex(0);
        const timer = window.setTimeout(() => {
            document.querySelector<HTMLInputElement>("[data-command-palette-input]")?.focus();
        }, 0);
        return () => window.clearTimeout(timer);
    }, [open]);

    const close = () => setOpen(false);
    const run = (action: () => void) => () => {
        close();
        action();
    };

    const unitSuffix = selectedUnitId ? `?unit=${encodeURIComponent(selectedUnitId)}` : "";

    const items = useMemo<PaletteItem[]>(() => {
        const list: PaletteItem[] = [];

        // 跳转视图
        PALETTE_VIEWS.forEach((viewName) => {
            const label = VIEW_LABELS[viewName] || viewName;
            list.push({
                key: `view:${viewName}`,
                section: "跳转视图",
                label,
                hint: viewName === "versions" ? "历史与审阅" : "创作阶段",
                keywords: `视图 ${label} ${viewName}`,
                icon: VIEW_ICONS[viewName],
                run: () => {
                    if (viewName === "timeline" || viewName === "versions") {
                        router.push(`/projects/${encodeURIComponent(projectId)}/${viewName}${unitSuffix}`);
                    } else {
                        setView(viewName as CanvasView);
                    }
                },
            });
        });

        // 搜索命中（FTS）
        const trimmed = query.trim();
        if (trimmed) {
            (searchQuery.data || []).slice(0, 8).forEach((hit) => {
                list.push({
                    key: `search:${hit.type}:${hit.id}`,
                    section: "搜索",
                    label: hit.title,
                    hint: `${hit.type === "unit" ? "单元" : "稿件"} · ${hit.snippet}`,
                    keywords: `搜索 ${hit.title} ${hit.snippet}`,
                    icon: <Search className="size-3.5" />,
                    run: () => {
                        if (hit.type === "unit") setSelectedUnit(hit.id);
                        else setSelectedUnit(hit.unit_id || null);
                    },
                });
            });
        }

        // 跳转单元
        unitOptions.slice(0, 30).forEach((option) => {
            list.push({
                key: `unit:${option.value}`,
                section: "跳转单元",
                label: option.label,
                hint: "创作单元",
                keywords: `单元 ${option.label}`,
                icon: <FolderPlus className="size-3.5" />,
                run: () => setSelectedUnit(option.value),
            });
        });

        // 操作
        list.push({
            key: "action:create-unit",
            section: "操作",
            label: "新建创作单元",
            hint: "打开结构面板的新建弹窗",
            keywords: "操作 新建 单元 create",
            icon: <FolderPlus className="size-3.5" />,
            run: () => requestUnitCreate(),
        });
        list.push({
            key: "action:structure",
            section: "操作",
            label: "展开 / 收起结构面板",
            hint: "⌘\\",
            keywords: "操作 结构 面板 structure",
            icon: <PanelLeft className="size-3.5" />,
            run: () => {
                if (structureInline) toggleStructure();
                else setStructureDrawer(true);
            },
        });
        list.push({
            key: "action:agent",
            section: "操作",
            label: "展开 / 收起助手面板",
            hint: "⌘J",
            keywords: "操作 助手 面板 agent",
            icon: <PanelRight className="size-3.5" />,
            run: () => {
                if (agentInline) toggleAgent();
                else setAgentDrawer(true);
            },
        });
        list.push({
            key: "action:dock",
            section: "操作",
            label: "展开 / 收起任务坞",
            hint: "底部任务进度",
            keywords: "操作 任务 任务坞 dock",
            icon: <UnfoldVertical className="size-3.5" />,
            run: () => toggleDock(),
        });
        list.push({
            key: "action:settings",
            section: "操作",
            label: "打开模型设置",
            hint: "配置 AI 渠道与模型",
            keywords: "操作 设置 模型 settings",
            icon: <Settings className="size-3.5" />,
            run: () => router.push("/settings"),
        });

        return list;
    }, [query, searchQuery.data, unitOptions, projectId, router, setSelectedUnit, setView, requestUnitCreate, structureInline, toggleStructure, setStructureDrawer, agentInline, toggleAgent, setAgentDrawer, toggleDock, unitSuffix, selectedUnitId]);

    const q = query.trim().toLowerCase();
    const visible = useMemo(() => items.filter((item) => !q || item.keywords.toLowerCase().includes(q)), [items, q]);

    useEffect(() => {
        setActiveIndex((current) => Math.min(current, Math.max(0, visible.length - 1)));
    }, [visible.length]);

    const handleKeyDown = (event: React.KeyboardEvent) => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            setActiveIndex((current) => Math.min(current + 1, visible.length - 1));
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((current) => Math.max(current - 1, 0));
        } else if (event.key === "Home") {
            event.preventDefault();
            setActiveIndex(0);
        } else if (event.key === "End") {
            event.preventDefault();
            setActiveIndex(visible.length - 1);
        } else if (event.key === "Enter") {
            const item = visible[activeIndex];
            if (item) {
                event.preventDefault();
                item.run();
            }
        }
    };

    const groups = SECTIONS.map((section) => ({
        section,
        items: visible.filter((item) => item.section === section),
    })).filter((group) => group.items.length > 0);

    let flatIndex = -1;

    return (
        <Modal open={open} onCancel={close} footer={null} closable={false} width={560} keyboard mask={{ closable: true }} title={null} styles={{ body: { padding: 0 } }} className="command-palette" aria-label="命令面板">
            <div onKeyDown={handleKeyDown} className="overflow-hidden rounded-[var(--r-lg)]">
                <div className="flex items-center gap-2 border-b border-[var(--hairline)] px-3 py-2.5">
                    <Search className="size-4 shrink-0 text-[var(--s-faint)]" />
                    <Input
                        data-command-palette-input
                        value={query}
                        onChange={(event) => {
                            setQuery(event.target.value);
                            setActiveIndex(0);
                        }}
                        placeholder="搜索视图、单元、稿件或执行动作…"
                        variant="borderless"
                        aria-label="命令面板搜索"
                        className="!px-1 !text-body"
                    />
                    <kbd className="shrink-0 rounded border border-[var(--hairline)] px-1.5 py-0.5 text-caption text-[var(--s-faint)]">Esc</kbd>
                </div>

                <div className="thin-scrollbar max-h-[420px] overflow-y-auto p-1.5">
                    {query.trim() && searchQuery.isFetching && !searchQuery.data ? <p className="px-3 py-4 text-center text-caption text-[var(--s-faint)]">搜索中…</p> : null}
                    {!groups.length ? <p className="px-3 py-8 text-center text-label text-[var(--s-faint)]">没有匹配的命令</p> : null}
                    {groups.map((group) => (
                        <div key={group.section} className="mb-1">
                            <div className="px-2 py-1.5 text-caption font-medium text-[var(--s-faint)]">{group.section}</div>
                            {group.items.map((item) => {
                                flatIndex += 1;
                                const index = flatIndex;
                                return (
                                    <button
                                        key={item.key}
                                        type="button"
                                        onClick={item.run}
                                        onMouseEnter={() => setActiveIndex(index)}
                                        className={cn("relative flex w-full items-center gap-2.5 rounded-[var(--r-sm)] px-2.5 py-2 text-left transition-colors", index === activeIndex ? "bg-[var(--s-raised)]" : "hover:bg-[var(--s-raised)]")}
                                    >
                                        {index === activeIndex ? <span aria-hidden className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--s-action)]" /> : null}
                                        <span className={cn("shrink-0", index === activeIndex ? "text-[var(--s-ink)]" : "text-[var(--s-faint)]")}>{item.icon}</span>
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-body text-[var(--s-ink)]">{item.label}</span>
                                            {item.hint ? <span className="block truncate text-caption text-[var(--s-faint)]">{item.hint}</span> : null}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    ))}
                </div>
            </div>
        </Modal>
    );
}
