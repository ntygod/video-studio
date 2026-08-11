"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    cancelJob,
    getJob,
    isJobActive,
    listJobs,
    retryJob,
    type Job,
    type JobDetail,
} from "@/services/api";
import { API_BASE } from "@/services/api/http";
import { applyJobStreamEvent, type JobStreamEvent } from "@/services/queries/job-stream-state";
import { qk } from "@/services/queries/keys";

const ACTIVE_POLL_MS = 2000;

/**
 * 订阅任务 SSE：job.progress / job.event / job.done 直接写进 React Query 缓存。
 * <p>
 * 任务坞改为 SSE 驱动，不再轮询；刷新页面后 SSE 会立即推当前快照。
 */
export function useJobStream(projectId?: string) {
    const client = useQueryClient();

    useEffect(() => {
        const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
        const source = new EventSource(`${API_BASE}/api/jobs/stream${params}`);

        const patchJob = (event: JobStreamEvent) => {
            const listKey = qk.jobs(projectId);
            client.setQueryData<Job[]>(listKey, (items) => {
                const list = items || [];
                const index = list.findIndex((job) => job.id === event.job_id);
                const base =
                    index >= 0
                        ? list[index]
                        : ({
                              id: event.job_id,
                              project_id: projectId || "",
                              unit_id: null,
                              job_type: "",
                              status: "queued",
                              progress: 0,
                              cancel_requested: false,
                              payload: {},
                              result: null,
                              error: "",
                              created_at: 0,
                              updated_at: 0,
                          } as Job);
                const next: Job = {
                    ...base,
                    status: (event.status as Job["status"]) || base.status,
                    progress: event.progress ?? base.progress,
                    result: (event.result as Job["result"]) ?? base.result,
                    // 后端时间戳已经是 Unix 秒，不能再次除以 1000。
                    updated_at: event.created_at ?? Date.now() / 1000,
                };
                const updated = [...list];
                if (index >= 0) updated[index] = next;
                else updated.push(next);
                return updated;
            });

            const detailKey = qk.job(event.job_id);
            client.setQueryData<JobDetail>(detailKey, (current) => {
                if (!current) return current;
                return applyJobStreamEvent(current, event);
            });
        };

        source.addEventListener("job.progress", (raw) => {
            try {
                patchJob({ type: "job.progress", ...JSON.parse((raw as MessageEvent).data) });
            } catch {
                /* 忽略坏帧 */
            }
        });
        source.addEventListener("job.event", (raw) => {
            try {
                patchJob({ type: "job.event", ...JSON.parse((raw as MessageEvent).data) });
            } catch {
                /* 忽略坏帧 */
            }
        });
        source.addEventListener("job.done", (raw) => {
            try {
                patchJob({ type: "job.done", ...JSON.parse((raw as MessageEvent).data) });
            } catch {
                /* 忽略坏帧 */
            }
        });

        return () => source.close();
    }, [client, projectId]);
}

/**
 * 任务列表。
 * <p>
 * 数据由 useJobStream 的 SSE 驱动；这里只在挂载/失效时拉一次。
 */
export function useJobs(projectId?: string) {
    return useQuery({
        queryKey: qk.jobs(projectId),
        queryFn: () => listJobs(projectId),
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
