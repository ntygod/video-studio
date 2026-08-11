import type { JobDetail, JobEvent, JobStatus } from "../api/types.ts";

export type JobStreamEvent = {
    id?: string;
    type: "job.progress" | "job.event" | "job.done";
    job_id: string;
    progress?: number;
    status?: string;
    result?: unknown;
    message?: string;
    level?: string;
    stage?: string;
    created_at?: number;
    parent_job_id?: string | null;
};

function eventTimestamp(createdAt?: number): number {
    return typeof createdAt === "number" ? createdAt : Date.now() / 1000;
}

function eventLevel(level?: string): JobEvent["level"] {
    if (level === "warning" || level === "warn") return "warn";
    if (level === "error") return "error";
    return "info";
}

function fallbackEventId(event: JobStreamEvent): string {
    return [
        "job-event",
        event.job_id,
        event.created_at ?? "unknown",
        event.stage ?? "",
        event.message ?? "",
    ].join(":");
}

export function applyJobStreamEvent(
    current: JobDetail,
    event: JobStreamEvent,
): JobDetail {
    const base: JobDetail = {
        ...current,
        status: (event.status as JobStatus | undefined) ?? current.status,
        progress: event.progress ?? current.progress,
        result: (event.result as JobDetail["result"] | undefined) ?? current.result,
        updated_at: eventTimestamp(event.created_at),
    };

    if (event.type !== "job.event") return base;

    const id = event.id || fallbackEventId(event);
    if ((base.events || []).some((item) => item.id === id)) return base;

    const item: JobEvent = {
        id,
        job_id: event.job_id,
        level: eventLevel(event.level),
        stage: event.stage || "",
        message: event.message || "",
        progress: event.progress ?? null,
        created_at: eventTimestamp(event.created_at),
    };
    return { ...base, events: [...(base.events || []), item] };
}
