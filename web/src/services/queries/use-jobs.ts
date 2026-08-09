"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { cancelJob, getJob, isJobActive, listJobs, retryJob, type Job, type JobDetail } from "@/services/api";
import { qk } from "@/services/queries/keys";

/** 有任务在跑时的轮询间隔。BE-3（SSE）落地后这条路径退化为降级方案。 */
const ACTIVE_POLL_MS = 3000;

/**
 * 任务列表。
 * <p>
 * 只在存在 queued/running 任务时轮询；全部结束后停止，避免现在这种"永远每 4 秒一次"的空转。
 */
export function useJobs(projectId?: string) {
    return useQuery({
        queryKey: qk.jobs(projectId),
        queryFn: () => listJobs(projectId),
        refetchInterval: (query) => {
            const jobs = query.state.data as Job[] | undefined;
            return jobs?.some(isJobActive) ? ACTIVE_POLL_MS : false;
        },
    });
}

/** 单个任务详情（含事件日志），同样只在任务未终结时轮询。 */
export function useJob(jobId: string | null) {
    return useQuery({
        queryKey: qk.job(jobId || ""),
        queryFn: () => getJob(jobId as string),
        enabled: Boolean(jobId),
        refetchInterval: (query) => {
            const job = query.state.data as JobDetail | undefined;
            return job && isJobActive(job) ? ACTIVE_POLL_MS : false;
        },
    });
}

function useJobMutation(action: (jobId: string) => Promise<Job>, projectId?: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: action,
        onSuccess: (job) => {
            client.invalidateQueries({ queryKey: qk.jobs(projectId) });
            client.invalidateQueries({ queryKey: qk.job(job.id) });
        },
    });
}

export function useCancelJob(projectId?: string) {
    return useJobMutation(cancelJob, projectId);
}

export function useRetryJob(projectId?: string) {
    return useJobMutation(retryJob, projectId);
}
