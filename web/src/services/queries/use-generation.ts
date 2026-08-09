"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { compileTimeline, renderTimeline, startGeneration, type GenerateInput } from "@/services/api";
import { qk } from "@/services/queries/keys";

/** 生成类任务提交后统一作废任务列表，让任务坞立刻显示新任务。 */
function useAfterJobSubmit(projectId: string) {
    const client = useQueryClient();
    return () => {
        client.invalidateQueries({ queryKey: qk.jobs(projectId) });
        client.invalidateQueries({ queryKey: qk.jobsRoot() });
    };
}

export function useStartGeneration(projectId: string) {
    const afterSubmit = useAfterJobSubmit(projectId);
    return useMutation({
        mutationFn: (input: GenerateInput) => startGeneration(projectId, input),
        onSuccess: afterSubmit,
    });
}

export function useCompileTimeline(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (input: { unit_id?: string | null; parameters?: Record<string, unknown> }) =>
            compileTimeline(projectId, input),
        onSuccess: () => {
            client.invalidateQueries({ queryKey: qk.project(projectId) });
            client.invalidateQueries({ queryKey: qk.artifactsRoot(projectId) });
        },
    });
}

export function useRenderTimeline(projectId: string) {
    const afterSubmit = useAfterJobSubmit(projectId);
    return useMutation({
        mutationFn: ({ timeline, name }: { timeline: Record<string, unknown>; name?: string }) =>
            renderTimeline(projectId, timeline, name),
        onSuccess: afterSubmit,
    });
}
