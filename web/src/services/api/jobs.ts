"use client";

import { get, post, seg } from "./http";
import type { Job, JobDetail } from "./types";

export function listJobs(projectId?: string) {
    return get<Job[]>("/api/jobs", { project_id: projectId });
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
