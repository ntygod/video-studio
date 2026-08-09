"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { App, Button, Drawer, Progress, Spin, Tag } from "antd";
import { Ban, ChevronRight, ExternalLink, RotateCw } from "lucide-react";
import Link from "next/link";

import { jobStatusMeta, jobTypeLabel } from "@/features/workspace/lib/labels";
import { isJobActive, mediaUrl } from "@/services/api";
import { useCancelJob, useJob, useJobs, useProjects, useRetryJob } from "@/services/queries";
import { absoluteTime, progressPercent } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

/** 从任务结果里挑出可直接打开的产物地址。 */
function resultUrlOf(result: Record<string, unknown> | null | undefined): string | undefined {
    if (!result) return undefined;
    for (const key of ["url", "uri", "final"]) {
        const value = result[key];
        if (typeof value === "string" && value) return mediaUrl(value);
    }
    return undefined;
}

function JobDetailDrawer({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
    const { message } = App.useApp();
    const { data: job } = useJob(jobId);
    const cancelJob = useCancelJob();
    const retryJob = useRetryJob();
    const logsEndRef = useRef<HTMLDivElement | null>(null);

    const events = useMemo(() => job?.events || [], [job?.events]);

    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [events.length]);

    const status = job?.status || "queued";
    const meta = jobStatusMeta(status);
    const resultUrl = resultUrlOf(job?.result);

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

    return (
        <Drawer title="任务详情" width={560} open={Boolean(jobId)} onClose={onClose} destroyOnHidden>
            {job ? (
                <div className="space-y-4">
                    <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                            <div className="truncate text-[13px] font-semibold text-[var(--studio-ink)]">
                                {jobTypeLabel(job.job_type)}
                            </div>
                            <div className="mt-0.5 text-[11px] text-[var(--studio-faint)]">{job.id}</div>
                        </div>
                        <Tag color={meta.color}>{meta.label}</Tag>
                    </div>

                    <Progress
                        percent={progressPercent(job.progress)}
                        status={status === "failed" ? "exception" : status === "succeeded" ? "success" : undefined}
                    />

                    {job.result ? (
                        <div className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] p-3">
                            <div className="mb-2 text-[11px] font-medium text-[var(--studio-muted)]">任务结果</div>
                            <pre className="hide-scrollbar overflow-x-auto font-mono text-[11px] leading-5 text-[var(--studio-ink)]">
                                {JSON.stringify(job.result, null, 2)}
                            </pre>
                            {resultUrl ? (
                                <a
                                    href={resultUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mt-2 inline-flex items-center gap-1 text-[11px] text-[var(--studio-action)] hover:underline"
                                >
                                    打开产物 <ExternalLink className="size-3" />
                                </a>
                            ) : null}
                        </div>
                    ) : null}

                    {job.error ? (
                        <div className="rounded-lg border border-[var(--studio-danger)]/40 bg-[var(--studio-danger)]/10 p-3 text-[11px] leading-5 text-[var(--studio-danger)]">
                            {job.error}
                        </div>
                    ) : null}

                    <div className="h-[300px] overflow-y-auto rounded-lg border border-[var(--studio-line)] bg-[var(--studio-bg)] p-3">
                        <div className="font-mono text-[11px] leading-5 text-[var(--studio-muted)]">
                            {events.length === 0 ? <div>等待任务输出…</div> : null}
                            {events.map((event) => (
                                <div key={event.id} className={event.level === "error" ? "text-[var(--studio-danger)]" : undefined}>
                                    [{new Date(event.created_at * 1000).toLocaleTimeString("zh-CN")}]
                                    {event.stage ? `[${event.stage}] ` : " "}
                                    {event.message}
                                    {typeof event.progress === "number" ? ` (${Math.round(event.progress)}%)` : ""}
                                </div>
                            ))}
                            <div ref={logsEndRef} />
                        </div>
                    </div>

                    <div className="flex gap-2">
                        {isJobActive(job) ? (
                            <Button danger icon={<Ban className="size-4" />} onClick={() => void run("cancel")}>
                                取消任务
                            </Button>
                        ) : null}
                        {job.status === "failed" ? (
                            <Button icon={<RotateCw className="size-4" />} onClick={() => void run("retry")}>
                                重试任务
                            </Button>
                        ) : null}
                    </div>
                </div>
            ) : (
                <div className="flex justify-center py-16">
                    <Spin />
                </div>
            )}
        </Drawer>
    );
}

/**
 * 全局任务中心（跨项目）。
 * <p>
 * 项目内的任务进度已经常驻在工作台底部的任务坞里，这里保留为跨项目的总览。
 * 只在存在未终结任务时轮询。
 */
export default function JobsPage() {
    const [detailId, setDetailId] = useState<string | null>(null);
    const jobsQuery = useJobs();
    const projectsQuery = useProjects();

    const jobs = jobsQuery.data || [];
    const projectTitles = useMemo(
        () => Object.fromEntries((projectsQuery.data || []).map((project) => [project.id, project.title])),
        [projectsQuery.data],
    );
    const activeCount = jobs.filter(isJobActive).length;

    return (
        <div className="mx-auto w-full max-w-[1100px] px-5 py-8 md:px-8">
            <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-[20px] font-semibold text-[var(--studio-ink)]">任务中心</h1>
                    <p className="mt-1 text-[13px] text-[var(--studio-muted)]">
                        所有生成与渲染任务持久化保存，重启后仍会恢复。
                        {activeCount ? ` 当前 ${activeCount} 个进行中，自动刷新。` : " 当前没有进行中的任务。"}
                    </p>
                </div>
                <Button icon={<RotateCw className="size-4" />} onClick={() => void jobsQuery.refetch()}>
                    刷新
                </Button>
            </header>

            {jobsQuery.error ? (
                <ErrorPanel title="任务加载失败" message={jobsQuery.error.message} onRetry={() => void jobsQuery.refetch()} />
            ) : jobsQuery.isLoading && !jobs.length ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : jobs.length === 0 ? (
                <EmptyState
                    title="暂无创作任务"
                    description="在项目里生成图片、视频或成片后，任务会出现在这里。"
                    action={
                        <Link href="/">
                            <Button type="primary">去创作</Button>
                        </Link>
                    }
                />
            ) : (
                <div className="space-y-2">
                    {jobs.map((job) => {
                        const meta = jobStatusMeta(job.status);
                        return (
                            <button
                                key={job.id}
                                type="button"
                                onClick={() => setDetailId(job.id)}
                                className="w-full rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-4 text-left transition-colors hover:border-[var(--studio-action-line)]"
                            >
                                <div className="flex flex-wrap items-center gap-3">
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2">
                                            <span className="truncate text-[13px] font-semibold text-[var(--studio-ink)]">
                                                {jobTypeLabel(job.job_type)} · {projectTitles[job.project_id] || "未知项目"}
                                            </span>
                                            <Tag color={meta.color} className="m-0">
                                                {meta.label}
                                            </Tag>
                                        </div>
                                        <div className="mt-1 text-[11px] text-[var(--studio-faint)]">
                                            创建于 {absoluteTime(job.created_at)}
                                        </div>
                                        {job.error ? (
                                            <div className="mt-1 truncate text-[11px] text-[var(--studio-danger)]">{job.error}</div>
                                        ) : null}
                                    </div>
                                    <div className="w-40">
                                        <Progress percent={progressPercent(job.progress)} size="small" showInfo={false} />
                                    </div>
                                    <ChevronRight className="size-4 text-[var(--studio-faint)]" />
                                </div>
                            </button>
                        );
                    })}
                </div>
            )}

            <JobDetailDrawer jobId={detailId} onClose={() => setDetailId(null)} />
        </div>
    );
}
