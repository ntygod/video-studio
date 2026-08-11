"use client";

import { get, post, seg } from "./http";
import type { Job, JobDetail, Page } from "./types";

export function listJobsPage(
    params: { project_id?: string | null; status?: string | null; limit?: number; cursor?: string | null } = {},
) {
    return get<Page<Job>>("/api/jobs", params);
}

/** 任务列表（分页行走）。 */
export async function listJobs(projectId?: string): Promise<Job[]> {
    const items: Job[] = [];
    let cursor: string | null = null;
    do {
        const page = await listJobsPage({ project_id: projectId, limit: 200, cursor });
        items.push(...page.items);
        cursor = page.next_cursor;
    } while (cursor);
    return items;
}

export function getJob(id: string) {
    return get<JobDetail>(`/api/jobs/${seg(id)}`);
}

export function cancelJob(id: string) {
    return post<Job>(`/api/jobs/${seg(id)}/cancel`);
}

export function retryJob(id: string) {
    return post<Job>(`/api/jobs/${seg(id)}/retry`);
}

export type JobCreateInput = {
    project_id: string;
    unit_id?: string | null;
    job_type: string;
    payload: Record<string, unknown>;
};

export function createJob(input: JobCreateInput) {
    return post<Job>("/api/jobs", input);
}

/** 任务是否处于未终结状态，用于决定是否继续轮询。 */
export function isJobActive(job: { status: string }): boolean {
    return job.status === "queued" || job.status === "running";
}
