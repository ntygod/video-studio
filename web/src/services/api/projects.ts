"use client";

import { del, get, patch, post, seg } from "./http";
import type { CreativeUnit, OkResult, Page, Project, ProjectDetail, ProjectSummary, SearchHit } from "./types";

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
    return get<Array<Project & Partial<ProjectSummary>>>("/api/projects");
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

export function listUnitsPage(
    projectId: string,
    params: { parent_id?: string | null; depth?: number; limit?: number; cursor?: string | null } = {},
) {
    return get<Page<CreativeUnit>>(`/api/projects/${seg(projectId)}/units`, params);
}

/** 拉取指定父级下的全部子单元（分页行走）。 */
export async function listUnits(projectId: string, parentId?: string): Promise<CreativeUnit[]> {
    const items: CreativeUnit[] = [];
    let cursor: string | null = null;
    do {
        const page = await listUnitsPage(projectId, { parent_id: parentId, limit: 200, cursor });
        items.push(...page.items);
        cursor = page.next_cursor;
    } while (cursor);
    return items;
}

/** FTS 全文检索（T3.2）。 */
export function searchProject(projectId: string, query: string, type = "all", limit = 20) {
    return get<SearchHit[]>(`/api/projects/${seg(projectId)}/search`, { q: query, type, limit });
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
