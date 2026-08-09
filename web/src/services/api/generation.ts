"use client";

import { post, seg } from "./http";
import type { Artifact, Job } from "./types";

export type CompileTimelineResult = {
    timeline: Record<string, unknown>;
    artifact: Artifact;
};

/** 把已确认的剪辑方案与素材编译成 TimelineIR。 */
export function compileTimeline(projectId: string, input: { unit_id?: string | null; parameters?: Record<string, unknown> }) {
    return post<CompileTimelineResult>(`/api/projects/${seg(projectId)}/timeline/compile`, input);
}

/** 提交渲染任务，返回的 Job 需要在任务坞里跟踪进度。 */
export function renderTimeline(projectId: string, timeline: Record<string, unknown>, name = "成片") {
    return post<Job>(`/api/projects/${seg(projectId)}/timeline/render`, { timeline, name });
}

export type GenerateInput = {
    capability: string;
    prompt?: string;
    schema_id?: string;
    artifact_kind?: string;
    artifact_name?: string;
    context?: Record<string, unknown>;
    parameters?: Record<string, unknown>;
};

/** 发起一次生成任务（llm / image / video / tts），返回持久化的 Job。 */
export function startGeneration(projectId: string, input: GenerateInput) {
    return post<Job>(`/api/projects/${seg(projectId)}/generate`, input);
}
