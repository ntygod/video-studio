"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Ban, ChevronRight, ExternalLink, Film, ImageIcon, Mic2, RefreshCw, RotateCw, Video } from "lucide-react";
import Link from "next/link";

import { jobStatusMeta, jobTypeLabel } from "@/features/workspace/lib/labels";
import { isJobActive, mediaUrl, type Job } from "@/services/api";
import { useCancelJob, useJob, useJobs, useProjects, useRetryJob } from "@/services/queries";
import { absoluteTime, progressPercent } from "@/shared/lib/format";
import { useMediaQuery } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";
import { Button, Drawer, Progress, Spin, Surface, Tag, Text, useApp } from "@/shared/ui";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

type StatusFilter = "all" | "active" | "failed" | "done";

function resultUrlOf(result: Record<string, unknown> | null | undefined): string | undefined {
    if (!result) return undefined;
    for (const key of ["url", "uri", "final"]) {
        const value = result[key];
        if (typeof value === "string" && value) return mediaUrl(value);
    }
    return undefined;
}

function jobIcon(job: Job) {
    if (job.job_type.includes("video") || job.job_type.includes("render")) return <Film className="size-4" />;
    if (job.job_type.includes("image")) return <ImageIcon className="size-4" />;
    if (job.job_type.includes("voice") || job.job_type.includes("tts")) return <Mic2 className="size-4" />;
    return <Video className="size-4" />;
}

function JobDetailContent({ jobId, projectTitle }: { jobId: string | null; projectTitle?: string }) {
    const { message } = useApp();
    const { data: job } = useJob(jobId);
    const cancelJob = useCancelJob();
    const retryJob = useRetryJob();
    const logsEndRef = useRef<HTMLDivElement | null>(null);

    const events = useMemo(() => job?.events || [], [job?.events]);

    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [events.length]);

    const run = async (action: "cancel" | "retry") => {
        if (!jobId) return;
        try {
            if (action === "cancel") await cancelJob.mutateAsync(jobId);
            else await retryJob.mutateAsync(jobId);
            message.success(action === "cancel" ? "已发送取消请求" : "已重新提交任务");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        }
    };

    if (!jobId) {
        return <EmptyState title="选择一个任务" description="查看进度、运行日志和任务产物。" />;
    }
    if (!job) {
        return (
            <div className="flex justify-center py-16">
                <Spin />
            </div>
        );
    }

    const meta = jobStatusMeta(job.status);
    const resultUrl = resultUrlOf(job.result);

    return (
        <div className="flex h-full flex-col">
            <div className="flex items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-[var(--s-muted)]">
                    {jobIcon(job)}
                </span>
                <div className="min-w-0 flex-1">
                    <Text as="h2" variant="body" tone="ink" weight={600} truncate>
                        {jobTypeLabel(job.job_type)}
                    </Text>
                    <Text variant="caption" tone="faint" className="mt-0.5 block">
                        {projectTitle || job.project_id}
                    </Text>
                </div>
                <Tag color={meta.color} className="m-0">
                    {meta.label}
                </Tag>
            </div>

            <div className="mt-4">
                <div className="mb-1 flex items-center justify-between text-caption text-[var(--s-muted)]">
                    <span>{job.status === "running" ? "正在处理" : meta.label}</span>
                    <span>{progressPercent(job.progress)}%</span>
                </div>
                <Progress value={progressPercent(job.progress) / 100} />
            </div>

            {job.error ? (
                <div className="mt-4 border-l-2 border-[var(--s-danger)] bg-[var(--s-raised)] px-3 py-2.5 text-caption leading-5 text-[var(--s-danger)]">
                    {job.error}
                </div>
            ) : null}

            <Surface level="canvas" radius="md" className="thin-scrollbar mt-4 min-h-48 flex-1 overflow-y-auto p-3">
                <div className="font-mono text-caption leading-5 text-[var(--s-muted)]">
                    {events.length === 0 ? <div>等待任务输出…</div> : null}
                    {events.map((event) => (
                        <div key={event.id} className={event.level === "error" ? "text-[var(--s-danger)]" : undefined}>
                            [{new Date(event.created_at * 1000).toLocaleTimeString("zh-CN")}]
                            {event.stage ? `[${event.stage}] ` : " "}
                            {event.message}
                            {typeof event.progress === "number" ? ` (${Math.round(event.progress)}%)` : ""}
                        </div>
                    ))}
                    <div ref={logsEndRef} />
                </div>
            </Surface>

            {job.result ? (
                <Surface level="raised" radius="md" className="mt-3 p-3">
                    <div className="flex items-center gap-2">
                        <div className="min-w-0 flex-1">
                            <Text variant="label" tone="ink" weight={500}>
                                任务产物已保存
                            </Text>
                            <Text variant="caption" tone="faint" truncate className="mt-0.5 block">
                                {JSON.stringify(job.result)}
                            </Text>
                        </div>
                        {resultUrl ? (
                            <a href={resultUrl} target="_blank" rel="noreferrer">
                                <Button size="sm" icon={<ExternalLink className="size-3.5" />}>
                                    打开
                                </Button>
                            </a>
                        ) : null}
                    </div>
                </Surface>
            ) : null}

            <div className="mt-3 flex flex-wrap gap-2">
                {isJobActive(job) ? (
                    <Button variant="danger" size="sm" icon={<Ban className="size-3.5" />} onClick={() => void run("cancel")}>
                        取消任务
                    </Button>
                ) : null}
                {job.status === "failed" ? (
                    <Button size="sm" icon={<RotateCw className="size-3.5" />} onClick={() => void run("retry")}>
                        重试任务
                    </Button>
                ) : null}
                <Link href={`/projects/${encodeURIComponent(job.project_id)}`}>
                    <Button size="sm" icon={<ExternalLink className="size-3.5" />}>
                        打开项目
                    </Button>
                </Link>
            </div>
        </div>
    );
}

function JobDetailDrawer({
    jobId,
    projectTitle,
    onClose,
}: {
    jobId: string | null;
    projectTitle?: string;
    onClose: () => void;
}) {
    return (
        <Drawer title="任务详情" size={560} open={Boolean(jobId)} onClose={onClose} destroyOnHidden>
            <JobDetailContent jobId={jobId} projectTitle={projectTitle} />
        </Drawer>
    );
}

export default function JobsPage() {
    const [detailId, setDetailId] = useState<string | null>(null);
    const [filter, setFilter] = useState<StatusFilter>("all");
    const inlineDetail = useMediaQuery("(min-width: 1280px)");
    const jobsQuery = useJobs();
    const projectsQuery = useProjects();

    const jobs = useMemo(() => jobsQuery.data || [], [jobsQuery.data]);
    const projectTitles = useMemo(
        () => Object.fromEntries((projectsQuery.data || []).map((project) => [project.id, project.title])),
        [projectsQuery.data],
    );
    const counts = useMemo(
        () => ({
            all: jobs.length,
            active: jobs.filter(isJobActive).length,
            failed: jobs.filter((job) => job.status === "failed").length,
            done: jobs.filter((job) => job.status === "succeeded" || job.status === "canceled").length,
        }),
        [jobs],
    );
    const filteredJobs = useMemo(() => {
        if (filter === "active") return jobs.filter(isJobActive);
        if (filter === "failed") return jobs.filter((job) => job.status === "failed");
        if (filter === "done") return jobs.filter((job) => job.status === "succeeded" || job.status === "canceled");
        return jobs;
    }, [filter, jobs]);
    const selectedId = detailId || (inlineDetail ? filteredJobs[0]?.id || null : null);
    const selectedJob = jobs.find((job) => job.id === selectedId);

    const tabs: Array<{ key: StatusFilter; label: string }> = [
        { key: "all", label: "全部" },
        { key: "active", label: "进行中" },
        { key: "failed", label: "失败" },
        { key: "done", label: "已完成" },
    ];

    return (
        <div className="mx-auto w-full max-w-[1320px] px-5 py-7 md:px-8 md:py-8">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--hairline)] pb-5">
                <div>
                    <Text as="h1" variant="title" tone="ink">
                        生产任务
                    </Text>
                    <Text as="p" variant="body" tone="muted" className="mt-1">
                        跨项目查看所有生成、配音、编译与渲染任务。
                    </Text>
                </div>
                <Button icon={<RefreshCw className="size-4" />} onClick={() => void jobsQuery.refetch()}>
                    刷新
                </Button>
            </header>

            {jobsQuery.error ? (
                <div className="mt-5">
                    <ErrorPanel title="任务加载失败" message={jobsQuery.error.message} onRetry={() => void jobsQuery.refetch()} />
                </div>
            ) : jobsQuery.isLoading && !jobs.length ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : jobs.length === 0 ? (
                <EmptyState
                    className="mt-5"
                    title="暂无创作任务"
                    description="在项目里生成图片、视频或成片后，任务会出现在这里。"
                    action={
                        <Link href="/">
                            <Button variant="primary">去创作</Button>
                        </Link>
                    }
                />
            ) : (
                <div className={cn("mt-5 grid gap-4", inlineDetail && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
                    <section className="min-w-0">
                        <div className="mb-3 flex flex-wrap gap-1">
                            {tabs.map((tab) => (
                                <button
                                    key={tab.key}
                                    type="button"
                                    onClick={() => {
                                        setFilter(tab.key);
                                        setDetailId(null);
                                    }}
                                    className={cn(
                                        "rounded-full px-3 py-1.5 text-caption transition-colors",
                                        filter === tab.key
                                            ? "bg-[var(--s-raised)] text-[var(--s-ink)]"
                                            : "text-[var(--s-muted)] hover:text-[var(--s-ink)]",
                                    )}
                                >
                                    {tab.label} {counts[tab.key]}
                                </button>
                            ))}
                        </div>

                        <div className="space-y-2">
                            {filteredJobs.map((job) => {
                                const meta = jobStatusMeta(job.status);
                                const active = job.id === selectedId;
                                return (
                                    <button
                                        key={job.id}
                                        type="button"
                                        onClick={() => setDetailId(job.id)}
                                        className={cn(
                                            "grid w-full grid-cols-[36px_minmax(0,1fr)_auto_18px] items-center gap-3 rounded-[var(--r-md)] border bg-[var(--s-panel)] p-3 text-left shadow-[var(--lift)] transition-colors md:grid-cols-[36px_minmax(160px,1fr)_96px_120px_18px]",
                                            active ? "border-[var(--hairline-strong)]" : "border-[var(--hairline)] hover:border-[var(--hairline-strong)]",
                                        )}
                                    >
                                        <span className="flex size-9 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-[var(--s-muted)]">
                                            {jobIcon(job)}
                                        </span>
                                        <span className="min-w-0">
                                            <Text as="span" variant="label" tone="ink" weight={500} truncate className="block">
                                                {jobTypeLabel(job.job_type)}
                                            </Text>
                                            <Text variant="caption" tone="faint" truncate className="mt-0.5 block">
                                                {projectTitles[job.project_id] || job.project_id} · {absoluteTime(job.updated_at)}
                                            </Text>
                                        </span>
                                        <Tag color={meta.color} className="m-0 hidden md:inline-flex">
                                            {meta.label}
                                        </Tag>
                                        <span className="hidden md:block">
                                            <span className="mb-1 flex justify-between text-caption text-[var(--s-muted)]">
                                                <span>{progressPercent(job.progress)}%</span>
                                            </span>
                                            <Progress value={progressPercent(job.progress) / 100} />
                                        </span>
                                        <ChevronRight className="size-4 text-[var(--s-faint)]" />
                                    </button>
                                );
                            })}
                        </div>
                    </section>

                    {inlineDetail ? (
                        <Surface as="aside" level="panel" radius="md" hairline lift className="min-h-[520px] p-4">
                            <JobDetailContent
                                jobId={selectedId}
                                projectTitle={selectedJob ? projectTitles[selectedJob.project_id] : undefined}
                            />
                        </Surface>
                    ) : null}
                </div>
            )}

            {!inlineDetail ? (
                <JobDetailDrawer
                    jobId={detailId}
                    projectTitle={selectedJob ? projectTitles[selectedJob.project_id] : undefined}
                    onClose={() => setDetailId(null)}
                />
            ) : null}
        </div>
    );
}
