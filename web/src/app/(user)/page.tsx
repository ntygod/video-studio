"use client";

import { useMemo, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { ArrowRight, LayoutGrid, Plus, Search, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { isCompletedStage, stageLabel } from "@/features/workspace/lib/labels";
import { SCRATCH_DRAFT_KEY, useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import type { Project, ProjectSummary } from "@/services/api";
import { mediaUrl } from "@/services/api/http";
import { useCreateProject, useDeleteProject, useProjects } from "@/services/queries";
import { relativeTime } from "@/shared/lib/format";
import { Button, Chip, IconButton, MediaFrame, Popconfirm, Spin, Surface, Text, Textarea, useApp } from "@/shared/ui";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

const SUGGESTIONS = [
    "制作一支 60 秒的夏日气泡水品牌短片",
    "把一个失踪宇航员的故事写成 5 集悬疑短剧",
    "为独立咖啡店策划一周的小红书内容",
];

function deriveTitle(concept: string): string {
    const firstLine = concept.split("\n")[0].trim();
    return firstLine.length > 20 ? `${firstLine.slice(0, 20)}…` : firstLine || "未命名项目";
}

function ProjectCard({
    project,
    index,
    onDelete,
}: {
    project: Project & Partial<ProjectSummary>;
    index: number;
    onDelete: (id: string) => void;
}) {
    const completed = isCompletedStage(project.stage);
    const cover = project.cover_asset_uri ? mediaUrl(project.cover_asset_uri) : "";
    const href = `/projects/${encodeURIComponent(project.id)}/story`;

    return (
        <article className="group overflow-hidden rounded-[var(--r-md)] border border-[var(--hairline)] bg-[var(--s-panel)] shadow-[var(--lift)] transition-[transform,border-color,box-shadow] duration-[var(--dur-base)] ease-[var(--ease-out)] hover:-translate-y-0.5 hover:border-[var(--hairline-strong)] hover:shadow-[var(--s-shadow-md)]">
            <Link href={href} aria-label={`打开项目 ${project.title}`}>
                <MediaFrame ratio="16 / 8.5" className="!rounded-none">
                    {cover ? (
                        <img src={cover} alt={project.title} loading="lazy" className="h-full w-full object-cover" />
                    ) : (
                        <div className="studio-project-cover flex h-full items-end p-4" data-tone={String(index % 4)}>
                            <Text variant="title" tone="ink" className="relative z-10 max-w-[90%] tracking-tight">
                                {project.title}
                            </Text>
                        </div>
                    )}
                    {project.pending_proposal_count ? (
                        <span className="absolute right-2 top-2 rounded-full bg-[var(--s-action-soft)] px-2 py-1 text-caption font-medium text-[var(--s-action)] backdrop-blur-md">
                            {project.pending_proposal_count} 条提案
                        </span>
                    ) : null}
                </MediaFrame>
            </Link>

            <div className="p-3.5">
                <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                        <Link href={href}>
                            <Text as="h2" variant="body" tone="ink" weight={600} truncate className="hover:text-[var(--s-action)]">
                                {project.title}
                            </Text>
                        </Link>
                        <Text as="p" variant="caption" tone="muted" className="mt-1 line-clamp-2 min-h-9 leading-5">
                            {project.brief.concept || "尚未定义创作方向，进入项目后和 AI 一起确定。"}
                        </Text>
                    </div>
                    <Popconfirm
                        title="删除整个项目和媒体文件？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={() => onDelete(project.id)}
                    >
                        <IconButton
                            label={`删除项目 ${project.title}`}
                            icon={<Trash2 className="size-3.5" />}
                            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                        />
                    </Popconfirm>
                </div>

                <div className="mt-3 flex items-center gap-2 border-t border-[var(--hairline)] pt-3">
                    <Chip tone={completed ? "success" : "info"}>{stageLabel(project.stage)}</Chip>
                    <Text variant="mono" tone="faint">
                        {project.unit_count ?? 0} 单元
                    </Text>
                    <Text variant="caption" tone="faint" className="ml-auto">
                        {relativeTime(project.last_activity ?? project.updated_at)}
                    </Text>
                    <Link href={href} aria-label={`进入 ${project.title}`}>
                        <ArrowRight className="size-3.5 text-[var(--s-muted)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--s-ink)]" />
                    </Link>
                </div>
            </div>
        </article>
    );
}

export default function ProjectsPage() {
    const router = useRouter();
    const { message } = useApp();
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
            setComposerDraft(SCRATCH_DRAFT_KEY, value);
            setConcept("");
            router.push(`/projects/${encodeURIComponent(project.id)}/brief`);
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
        <div className="mx-auto w-full max-w-[1280px] px-5 py-7 md:px-8 md:py-8">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--hairline)] pb-5">
                <div>
                    <Text as="h1" variant="title" tone="ink">
                        创作项目
                    </Text>
                    <Text as="p" variant="body" tone="muted" className="mt-1">
                        让项目从一个明确意图开始，结构和形式由内容决定。
                    </Text>
                </div>
                <div className="flex items-center gap-2">
                    <Button size="sm" icon={<SlidersHorizontal className="size-3.5" />}>
                        筛选
                    </Button>
                    <Button size="sm" icon={<Search className="size-3.5" />}>
                        搜索
                    </Button>
                </div>
            </header>

            <Surface as="section" level="panel" radius="lg" hairline lift className="mt-5 p-4 md:p-5">
                <div className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
                    <div>
                        <Text as="h2" variant="heading" tone="ink">
                            下一部作品，从一句话开始
                        </Text>
                        <Textarea
                            value={concept}
                            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setConcept(event.target.value)}
                            onPressEnter={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                                if (event.shiftKey) return;
                                event.preventDefault();
                                void start();
                            }}
                            placeholder="例如：制作一支 60 秒的夏日气泡水品牌短片，清爽、克制、有一点超现实。"
                            autoSize={{ minRows: 2, maxRows: 5 }}
                            variant="borderless"
                            className="!mt-2 !bg-transparent !px-0 !text-body"
                        />
                        <div className="mt-2 flex flex-wrap gap-1.5">
                            {SUGGESTIONS.map((item) => (
                                <Chip key={item} tone="default" onClick={() => setConcept(item)}>
                                    {item}
                                </Chip>
                            ))}
                        </div>
                    </div>
                    <Button
                        variant="primary"
                        disabled={!concept.trim()}
                        loading={createProject.isPending}
                        icon={<Sparkles className="size-4" />}
                        onClick={() => void start()}
                    >
                        建立项目
                    </Button>
                </div>
            </Surface>

            <div className="mt-7 flex items-end justify-between gap-3">
                <div>
                    <Text as="h2" variant="heading" tone="ink">
                        最近创作
                    </Text>
                    <Text variant="caption" tone="faint" className="mt-1 block">
                        共 {stats.total} · 进行中 {stats.active} · 已完成 {stats.completed}
                    </Text>
                </div>
                <IconButton label="网格视图" icon={<LayoutGrid className="size-4" />} active />
            </div>

            {projectsQuery.error ? (
                <div className="mt-5">
                    <ErrorPanel title="项目加载失败" message={projectsQuery.error.message} onRetry={() => void projectsQuery.refetch()} />
                </div>
            ) : projectsQuery.isLoading ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : projects.length === 0 ? (
                <EmptyState
                    className="mt-5"
                    icon={<Plus className="size-6" />}
                    title="还没有项目"
                    description="在上面的输入框里写一句话，就能创建第一个项目。"
                />
            ) : (
                <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {projects.map((project, index) => (
                        <ProjectCard key={project.id} project={project} index={index} onDelete={(id) => void remove(id)} />
                    ))}
                </div>
            )}
        </div>
    );
}
