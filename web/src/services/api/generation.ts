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
    unit_id?: string | null;
    prompt?: string;
    prompt_version?: string;
    schema_id?: string;
    artifact_kind?: string;
    artifact_name?: string;
    input_version_ids?: string[];
    input_asset_ids?: string[];
    context?: Record<string, unknown>;
    parameters?: Record<string, unknown>;
};

/** 发起一次生成任务（llm / image / video / tts），返回持久化的 Job。 */
export function startGeneration(projectId: string, input: GenerateInput) {
    return post<Job>(`/api/projects/${seg(projectId)}/generate`, input);
}

export type BatchGenerateInput = {
    unit_ids: string[];
    capability: string;
    prompt_template: string;
    params?: Record<string, unknown>;
};

export type BatchGenerateResult = {
    parent_job_id: string;
    child_job_ids: string[];
};

/** 批量生成：父任务进度 = 子任务完成比例。 */
export function generateBatch(projectId: string, input: BatchGenerateInput) {
    return post<BatchGenerateResult>(`/api/projects/${seg(projectId)}/generate/batch`, input);
}
