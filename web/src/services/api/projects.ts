"use client";

import { del, get, patch, post, seg } from "./http";
import type { CreativeUnit, OkResult, Project, ProjectDetail } from "./types";

/** 创建项目的入参。project_type / workflow_id / format_id 均为开放文本。 */
export type ProjectCreateInput = {
    title: string;
    concept?: string;
    project_type?: string;
    workflow_id?: string;
    format_id?: string;
    custom_fields?: Record<string, unknown>;
};

export function listProjects() {
    return get<Project[]>("/api/projects");
}

export function getProject(id: string) {
    return get<ProjectDetail>(`/api/projects/${seg(id)}`);
}

export function createProject(input: ProjectCreateInput) {
    return post<Project>("/api/projects", {
        project_type: "freeform",
        workflow_id: "freeform",
        format_id: "freeform",
        ...input,
    });
}

/**
 * 更新项目。
 * <p>
 * 后端使用乐观锁：expectedRevision 与当前 revision 不一致时返回 409，调用方需重新拉取后重试。
 */
export function updateProject(id: string, expectedRevision: number, projectPatch: Partial<Project>) {
    return patch<Project>(`/api/projects/${seg(id)}`, {
        expected_revision: expectedRevision,
        patch: projectPatch,
    });
}

export function deleteProject(id: string) {
    return del<OkResult>(`/api/projects/${seg(id)}`);
}

export type UnitInput = Partial<CreativeUnit> & { title: string };

export function listUnits(projectId: string, parentId?: string) {
    return get<CreativeUnit[]>(`/api/projects/${seg(projectId)}/units`, { parent_id: parentId });
}

export function createUnits(projectId: string, units: UnitInput[]) {
    return post<CreativeUnit[]>(`/api/projects/${seg(projectId)}/units`, { units });
}

export function updateUnit(projectId: string, unitId: string, unitPatch: Partial<CreativeUnit>) {
    return patch<CreativeUnit>(`/api/projects/${seg(projectId)}/units/${seg(unitId)}`, unitPatch);
}

export function deleteUnit(projectId: string, unitId: string) {
    return del<OkResult>(`/api/projects/${seg(projectId)}/units/${seg(unitId)}`);
}
