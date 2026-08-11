"use client";

import { useEffect, useRef, useState } from "react";
import { Ban, ChevronDown, ChevronUp, RotateCw } from "lucide-react";

import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { jobStatusMeta, jobTypeLabel } from "@/features/workspace/lib/labels";
import { isJobActive, type Job } from "@/services/api";
import { useCancelJob, useJobs, useJobStream, useRetryJob } from "@/services/queries";
import { progressPercent, relativeTime } from "@/shared/lib/format";
import { StatusDot } from "@/shared/ui/indicators";
import { Button, Progress, Tooltip, useApp } from "@/shared/ui";

function statusTone(status: string) {
    if (status === "running" || status === "queued") return "active" as const;
    if (status === "succeeded") return "success" as const;
    if (status === "failed") return "error" as const;
    if (status === "canceled") return "warning" as const;
    return "idle" as const;
}

/** 折叠态的一行摘要：优先显示正在跑的任务，其次是失败的。 */
function summarize(jobs: Job[]): string {
    if (!jobs.length) return "暂无任务";
    const active = jobs.filter(isJobActive);
    const failed = jobs.filter((job) => job.status === "failed");
    const parts: string[] = [];
    if (active.length) parts.push(`${active.length} 个任务运行中`);
    if (failed.length) parts.push(`${failed.length} 个失败`);
    if (!parts.length) parts.push(`最近 ${jobs.length} 个任务已完成`);
    return parts.join(" · ");
}

function JobRow({ job, projectId }: { job: Job; projectId: string }) {
    const { message } = useApp();
    const cancelJob = useCancelJob(projectId);
    const retryJob = useRetryJob(projectId);
    const meta = jobStatusMeta(job.status);
    const active = isJobActive(job);

    const run = async (action: "cancel" | "retry") => {
        try {
            if (action === "cancel") await cancelJob.mutateAsync(job.id);
            else await retryJob.mutateAsync(job.id);
            message.success(action === "cancel" ? "已发送取消请求" : "已重新提交任务");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        }
    };

    return (
        <div className="flex items-center gap-3 border-b border-[var(--hairline)] px-3 py-2 last:border-b-0">
            <StatusDot tone={statusTone(job.status)} pulse={job.status === "running"} />
            <span className="w-24 shrink-0 truncate text-label text-[var(--s-ink)]">{jobTypeLabel(job.job_type)}</span>
            <span className="w-16 shrink-0 text-caption text-[var(--s-muted)]">{meta.label}</span>
            <div className="w-32 shrink-0">
                <Progress value={progressPercent(job.progress) / 100} />
            </div>
            <span className="min-w-0 flex-1 truncate text-caption text-[var(--s-faint)]">
                {job.error || relativeTime(job.updated_at)}
            </span>
            <div className="flex shrink-0 items-center gap-1">
                {active ? (
                    <Tooltip title="取消任务">
                        <Button size="sm" variant="ghost" aria-label="取消任务" icon={<Ban className="size-3.5" />} onClick={() => void run("cancel")} />
                    </Tooltip>
                ) : null}
                {job.status === "failed" ? (
                    <Tooltip title="重试任务">
                        <Button size="sm" variant="ghost" aria-label="重试任务" icon={<RotateCw className="size-3.5" />} onClick={() => void run("retry")} />
                    </Tooltip>
                ) : null}
            </div>
        </div>
    );
}

/**
 * 底部任务坞。
 * <p>
 * 折叠时只占一行，把生产状态常驻在工作台里，不必再跳到独立的任务页。
 * 数据源只在存在未终结任务时轮询。
 */
export function JobDock() {
    const { projectId } = useWorkspaceRoute();
    const expanded = useWorkspaceStore((state) => state.dockExpanded);
    const toggleDock = useWorkspaceStore((state) => state.toggleDock);
    const { data } = useJobs(projectId);
    useJobStream(projectId);

    const jobs = data || [];
    const activeCount = jobs.filter(isJobActive).length;

    // T5.3：任务结束（成功/失败）时向屏幕阅读器播报一次，避免反复朗读整份列表。
    const announced = useRef<Set<string>>(new Set());
    const [announcement, setAnnouncement] = useState("");
    useEffect(() => {
        if (!jobs.length) return;
        const finished = jobs.filter((job) => job.status === "succeeded" || job.status === "failed");
        const fresh = finished.filter((job) => !announced.current.has(job.id));
        if (!fresh.length) return;
        fresh.forEach((job) => announced.current.add(job.id));
        setAnnouncement(
            fresh
                .map((job) => `${jobTypeLabel(job.job_type)}${job.status === "succeeded" ? "已完成" : "失败"}`)
                .join("，"),
        );
    }, [jobs]);

    return (
        <div className="shrink-0 border-t border-[var(--hairline)] bg-[var(--s-panel)]">
            <div role="status" aria-live="polite" className="sr-only">
                {announcement}
            </div>
            <button
                type="button"
                onClick={toggleDock}
                aria-expanded={expanded}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-[var(--s-raised)]"
            >
                {activeCount ? <StatusDot tone="active" pulse /> : <StatusDot tone="idle" />}
                <span className="text-caption text-[var(--s-text)]">{summarize(jobs)}</span>
                <span className="flex-1" />
                <span className="text-caption text-[var(--s-faint)]">{expanded ? "收起" : "展开"}</span>
                {expanded ? (
                    <ChevronDown className="size-3.5 text-[var(--s-faint)]" />
                ) : (
                    <ChevronUp className="size-3.5 text-[var(--s-faint)]" />
                )}
            </button>

            {expanded ? (
                <div className="hide-scrollbar max-h-[220px] overflow-y-auto border-t border-[var(--hairline)]">
                    {jobs.length ? (
                        jobs.map((job) => <JobRow key={job.id} job={job} projectId={projectId} />)
                    ) : (
                        <p className="px-3 py-6 text-center text-caption text-[var(--s-faint)]">
                            这个项目还没有生成或渲染任务
                        </p>
                    )}
                </div>
            ) : null}
        </div>
    );
}
