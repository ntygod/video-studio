"use client";

import { useMemo, useState } from "react";
import { App, Button, Input, Popconfirm, Spin, Tag } from "antd";
import { ArrowRight, Boxes, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { SCRATCH_DRAFT_KEY, useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { isCompletedStage, stageLabel } from "@/features/workspace/lib/labels";
import type { Project } from "@/services/api";
import { useCreateProject, useDeleteProject, useProjects } from "@/services/queries";
import { relativeTime } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

/** 起始输入框下方的灵感示例。 */
const SUGGESTIONS = [
    "制作一支 60 秒的夏日气泡水品牌短片",
    "把一个失踪宇航员的故事写成 5 集悬疑短剧",
    "为独立咖啡店策划一周的小红书图文内容",
    "创作一首赛博朋克歌曲，并配套封面和 MV 分镜",
];

/** 从一句话里截出项目名。 */
function deriveTitle(concept: string): string {
    const firstLine = concept.split("\n")[0].trim();
    return firstLine.length > 20 ? `${firstLine.slice(0, 20)}…` : firstLine || "未命名项目";
}

function ProjectCard({ project, onDelete }: { project: Project; onDelete: (id: string) => void }) {
    const completed = isCompletedStage(project.stage);
    return (
        <article className="group flex flex-col rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5 transition-colors hover:border-[var(--studio-action-line)]">
            <div className="flex items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--studio-action-soft)] text-[var(--studio-action)]">
                    <Boxes className="size-4.5" />
                </span>
                <div className="min-w-0 flex-1">
                    <h2 className="truncate text-[14px] font-semibold text-[var(--studio-ink)]">{project.title}</h2>
                    <div className="mt-0.5 text-[11px] text-[var(--studio-faint)]">
                        更新于 {relativeTime(project.updated_at)}
                    </div>
                </div>
                <Popconfirm
                    title="删除整个项目和媒体文件？"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => onDelete(project.id)}
                >
                    <Button
                        type="text"
                        size="small"
                        aria-label={`删除项目 ${project.title}`}
                        icon={<Trash2 className="size-4" />}
                        className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    />
                </Popconfirm>
            </div>

            <p className="mt-4 line-clamp-3 min-h-[57px] text-[13px] leading-[19px] text-[var(--studio-muted)]">
                {project.brief.concept || "尚未定义创作方向，进入项目后和 AI 一起确定。"}
            </p>

            <div className="mt-4 flex items-center justify-between gap-2">
                <Tag color={completed ? "green" : "blue"} className="m-0">
                    {stageLabel(project.stage)}
                </Tag>
                <Link href={`/projects/${encodeURIComponent(project.id)}`}>
                    <Button size="small" icon={<ArrowRight className="size-3.5" />}>
                        打开工作台
                    </Button>
                </Link>
            </div>
        </article>
    );
}

/**
 * 项目库。
 * <p>
 * 直接从一句话开始：输入内容即创建项目并把这句话带进工作台的对话输入框，
 * 省掉旧版"点新建 → 填弹窗表单 → 进项目 → 再自己开对话"的四步。
 */
export default function ProjectsPage() {
    const router = useRouter();
    const { message } = App.useApp();
    const [concept, setConcept] = useState("");

    const projectsQuery = useProjects();
    const createProject = useCreateProject();
    const deleteProject = useDeleteProject();
    const setComposerDraft = useWorkspaceStore((state) => state.setComposerDraft);

    const projects = useMemo(() => projectsQuery.data || [], [projectsQuery.data]);
    const stats = useMemo(() => {
        const active = projects.filter((item) => !isCompletedStage(item.stage)).length;
        return { total: projects.length, active, completed: projects.length - active };
    }, [projects]);

    const start = async () => {
        const value = concept.trim();
        if (!value || createProject.isPending) return;
        try {
            const project = await createProject.mutateAsync({ title: deriveTitle(value), concept: value });
            // 把这句话预填进助手输入框，进去后一按发送就能开始。
            setComposerDraft(SCRATCH_DRAFT_KEY, value);
            setConcept("");
            router.push(`/projects/${encodeURIComponent(project.id)}`);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "项目创建失败");
        }
    };

    const remove = async (id: string) => {
        try {
            await deleteProject.mutateAsync(id);
            message.success("项目已删除");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-8">
            <section className="mx-auto max-w-[680px] text-center">
                <h1 className="text-[26px] font-semibold text-[var(--studio-ink)]">你想创作什么？</h1>
                <p className="mt-2 text-[13px] text-[var(--studio-muted)]">
                    一句话就能开始。项目类型、结构和数量都由你定，系统不预设边界。
                </p>

                <div className="mt-6 rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-3 text-left transition-colors focus-within:border-[var(--studio-action-line)]">
                    <Input.TextArea
                        value={concept}
                        onChange={(event) => setConcept(event.target.value)}
                        onPressEnter={(event) => {
                            if (event.shiftKey) return;
                            event.preventDefault();
                            void start();
                        }}
                        placeholder="例如：把一个失踪宇航员的故事写成 5 集悬疑短剧"
                        autoSize={{ minRows: 2, maxRows: 6 }}
                        variant="borderless"
                        className="!px-1 !text-[14px]"
                    />
                    <div className="mt-2 flex justify-end">
                        <Button
                            type="primary"
                            disabled={!concept.trim()}
                            loading={createProject.isPending}
                            icon={<ArrowRight className="size-4" />}
                            onClick={() => void start()}
                        >
                            开始创作
                        </Button>
                    </div>
                </div>

                <div className="mt-3 flex flex-wrap justify-center gap-1.5">
                    {SUGGESTIONS.map((item) => (
                        <button
                            key={item}
                            type="button"
                            onClick={() => setConcept(item)}
                            className="rounded-full border border-[var(--studio-line)] px-2.5 py-1 text-[11px] text-[var(--studio-muted)] transition-colors hover:border-[var(--studio-action-line)] hover:text-[var(--studio-ink)]"
                        >
                            {item}
                        </button>
                    ))}
                </div>
            </section>

            <div className="mt-12 flex items-center justify-between gap-3 border-b border-[var(--studio-line)] pb-3">
                <h2 className="text-[14px] font-semibold text-[var(--studio-ink)]">我的创作</h2>
                <div className="text-[11px] text-[var(--studio-faint)]">
                    共 {stats.total} 个 · 进行中 {stats.active} · 已完成 {stats.completed}
                </div>
            </div>

            {projectsQuery.error ? (
                <ErrorPanel
                    title="项目加载失败"
                    message={projectsQuery.error.message}
                    onRetry={() => void projectsQuery.refetch()}
                />
            ) : projectsQuery.isLoading ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : projects.length === 0 ? (
                <EmptyState
                    className="mt-6"
                    icon={<Plus className="size-6" />}
                    title="还没有项目"
                    description="在上面的输入框里写一句话，就能创建第一个项目。"
                />
            ) : (
                <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {projects.map((project) => (
                        <ProjectCard key={project.id} project={project} onDelete={(id) => void remove(id)} />
                    ))}
                </div>
            )}
        </div>
    );
}
