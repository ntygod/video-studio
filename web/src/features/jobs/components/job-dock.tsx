"use client";

import { App, Button, Progress, Tooltip } from "antd";
import { Ban, ChevronDown, ChevronUp, RotateCw } from "lucide-react";

import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { jobStatusMeta, jobTypeLabel } from "@/features/workspace/lib/labels";
import { isJobActive, type Job } from "@/services/api";
import { useCancelJob, useJobs, useRetryJob } from "@/services/queries";
import { progressPercent, relativeTime } from "@/shared/lib/format";
import { StatusDot } from "@/shared/ui/indicators";

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
    const { message } = App.useApp();
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
        <div className="flex items-center gap-3 border-b border-[var(--studio-line)] px-3 py-2 last:border-b-0">
            <StatusDot tone={statusTone(job.status)} pulse={job.status === "running"} />
            <span className="w-24 shrink-0 truncate text-[12px] text-[var(--studio-ink)]">{jobTypeLabel(job.job_type)}</span>
            <span className="w-16 shrink-0 text-[11px] text-[var(--studio-muted)]">{meta.label}</span>
            <div className="w-32 shrink-0">
                <Progress percent={progressPercent(job.progress)} size="small" showInfo={false} />
            </div>
            <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--studio-faint)]">
                {job.error || relativeTime(job.updated_at)}
            </span>
            <div className="flex shrink-0 items-center gap-1">
                {active ? (
                    <Tooltip title="取消任务">
                        <Button size="small" type="text" aria-label="取消任务" icon={<Ban className="size-3.5" />} onClick={() => void run("cancel")} />
                    </Tooltip>
                ) : null}
                {job.status === "failed" ? (
                    <Tooltip title="重试任务">
                        <Button size="small" type="text" aria-label="重试任务" icon={<RotateCw className="size-3.5" />} onClick={() => void run("retry")} />
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

    const jobs = data || [];
    const activeCount = jobs.filter(isJobActive).length;

    return (
        <div className="shrink-0 border-t border-[var(--studio-line)] bg-[var(--studio-surface)]">
            <button
                type="button"
                onClick={toggleDock}
                aria-expanded={expanded}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-[var(--studio-surface-hover)]"
            >
                {activeCount ? <StatusDot tone="active" pulse /> : <StatusDot tone="idle" />}
                <span className="text-[11px] text-[var(--studio-text)]">{summarize(jobs)}</span>
                <span className="flex-1" />
                <span className="text-[11px] text-[var(--studio-faint)]">{expanded ? "收起" : "展开"}</span>
                {expanded ? (
                    <ChevronDown className="size-3.5 text-[var(--studio-faint)]" />
                ) : (
                    <ChevronUp className="size-3.5 text-[var(--studio-faint)]" />
                )}
            </button>

            {expanded ? (
                <div className="hide-scrollbar max-h-[220px] overflow-y-auto border-t border-[var(--studio-line)]">
                    {jobs.length ? (
                        jobs.map((job) => <JobRow key={job.id} job={job} projectId={projectId} />)
                    ) : (
                        <p className="px-3 py-6 text-center text-[11px] text-[var(--studio-faint)]">
                            这个项目还没有生成或渲染任务
                        </p>
                    )}
                </div>
            ) : null}
        </div>
    );
}
