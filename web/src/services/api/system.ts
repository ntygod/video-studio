"use client";

import { del, get, patch, post, seg } from "./http";
import type { HealthStatus, OkResult, Workflow } from "./types";

export function checkHealth() {
    return get<HealthStatus>("/api/health");
}

export function listWorkflows() {
    return get<Workflow[]>("/api/workflows");
}

export function createWorkflow(input: { name: string; description?: string; definition?: Record<string, unknown> }) {
    return post<Workflow>("/api/workflows", input);
}

export function updateWorkflow(id: string, input: Partial<Workflow>) {
    return patch<Workflow>(`/api/workflows/${seg(id)}`, input);
}

export function deleteWorkflow(id: string) {
    return del<OkResult>(`/api/workflows/${seg(id)}`);
}
