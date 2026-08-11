"use client";

import { useEffect, useState } from "react";
import { BookMarked, Pin, PinOff } from "lucide-react";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useUpdateProject } from "@/services/queries";
import { cn } from "@/shared/lib/utils";
import { Popover, Text, useApp } from "@/shared/ui";

const SECTIONS = [
    { key: "characters", label: "角色", hint: (value: unknown) => `${Array.isArray(value) ? value.length : 0} 个角色` },
    { key: "world", label: "世界", hint: (value: unknown) => (value && typeof value === "object" && "premise" in (value as Record<string, unknown>) ? String((value as Record<string, unknown>).premise || "").slice(0, 24) : "") },
    { key: "style", label: "风格", hint: (value: unknown) => (value && typeof value === "object" && "visual_direction" in (value as Record<string, unknown>) ? String((value as Record<string, unknown>).visual_direction || "").slice(0, 24) : "") },
] as const;

type PinnedRef = { type: string; section?: string; id?: string };

/**
 * 圣经面板（T3.F3）：角色/世界/风格常驻入口，浮层展示，每项可钉到上下文。
 * <p>
 * 钉住状态写入 ProjectSettings.pinned_refs，后端每轮 Agent 上下文自动注入。
 */
export function BiblePanelButton() {
    const { message } = useApp();
    const { project, projectId } = useWorkspaceData();
    const updateProject = useUpdateProject(projectId);
    const [open, setOpen] = useState(false);

    const bible = project?.bible;
    const pinnedRefs = (project?.settings.pinned_refs || []) as PinnedRef[];

    const isPinned = (section: string) =>
        pinnedRefs.some((ref) => ref.type === "bible" && (ref.section || ref.id) === section);

    // T5.2：Esc 关闭浮层（antd v6 Popover 不再内置 keyboard 关闭）。
    useEffect(() => {
        if (!open) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [open]);

    const togglePin = async (section: string) => {
        if (!project) return;
        const rest = pinnedRefs.filter(
            (ref) => !(ref.type === "bible" && (ref.section || ref.id) === section),
        );
        const next = isPinned(section) ? rest : [...rest, { type: "bible", section }];
        try {
            await updateProject.mutateAsync({
                expectedRevision: project.revision,
                patch: { settings: { ...project.settings, pinned_refs: next } },
            });
        } catch (error) {
            message.error(error instanceof Error ? error.message : "钉住失败");
        }
    };

    return (
        <Popover
            open={open}
            onOpenChange={setOpen}
            trigger="click"
            placement="rightTop"
            content={
                <div className="w-[300px] p-1">
                    <Text variant="label" tone="ink" weight={600} className="px-2 py-1.5 block">
                        创作设定（Bible）
                    </Text>
                    {bible ? (
                        <div className="space-y-1">
                            {SECTIONS.map((section) => {
                                const value = (bible as unknown as Record<string, unknown>)[section.key];
                                const pinned = isPinned(section.key);
                                return (
                                    <div
                                        key={section.key}
                                        className="flex items-center gap-2 rounded-[var(--r-sm)] px-2 py-2 transition-colors hover:bg-[var(--s-raised)]"
                                    >
                                        <div className="min-w-0 flex-1">
                                            <Text variant="label" tone="ink">
                                                {section.label}
                                            </Text>
                                            <Text variant="caption" tone="faint" truncate className="block">
                                                {section.hint(value) || "未建立"}
                                            </Text>
                                        </div>
                                        <button
                                            type="button"
                                            aria-label={pinned ? `取消钉住 ${section.label}` : `钉住 ${section.label} 到上下文`}
                                            onClick={() => void togglePin(section.key)}
                                            className={cn(
                                                "flex size-7 shrink-0 items-center justify-center rounded-[var(--r-sm)] transition-colors",
                                                pinned
                                                    ? "bg-[var(--s-raised)] text-[var(--s-ink)]"
                                                    : "text-[var(--s-faint)] hover:bg-[var(--s-raised)]",
                                            )}
                                        >
                                            {pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
                                        </button>
                                    </div>
                                );
                            })}
                            <p className="px-2 pt-1 text-caption leading-4 text-[var(--s-faint)]">
                                钉住的片段会在每一轮 Agent 上下文里自动注入。
                            </p>
                        </div>
                    ) : (
                        <p className="px-2 py-4 text-center text-caption text-[var(--s-faint)]">设定尚未加载</p>
                    )}
                </div>
            }
        >
            <button
                type="button"
                aria-haspopup="dialog"
                aria-expanded={open}
                className="flex w-full items-center gap-2 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-label text-[var(--s-text)] transition-colors hover:bg-[var(--s-raised)] hover:text-[var(--s-ink)]"
            >
                <BookMarked className="size-4 shrink-0 text-[var(--s-faint)]" />
                <span className="min-w-0 flex-1 truncate">创作设定</span>
                <span className="shrink-0 text-caption text-[var(--s-faint)]">
                    {bible?.characters.length ? `${bible.characters.length} 角色` : "未建立"}
                </span>
            </button>
        </Popover>
    );
}
