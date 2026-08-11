"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createUnits, deleteUnit, listUnitsPage, updateUnit, type CreativeUnit, type UnitInput } from "@/services/api";
import { qk } from "@/services/queries/keys";

/** 分页行走拉取整棵单元树（每层按 parent_id 展开），返回扁平列表。 */
export async function fetchAllUnits(projectId: string): Promise<CreativeUnit[]> {
    const seen = new Map<string, CreativeUnit>();
    const queue: Array<string | null> = [null];
    while (queue.length) {
        const parentId = queue.shift() as string | null;
        let cursor: string | null = null;
        do {
            const page = await listUnitsPage(projectId, { parent_id: parentId, depth: 1, limit: 200, cursor });
            page.items.forEach((unit) => {
                if (!seen.has(unit.id)) {
                    seen.set(unit.id, unit);
                    queue.push(unit.id);
                }
            });
            cursor = page.next_cursor;
        } while (cursor);
    }
    return [...seen.values()];
}

/** 项目全部单元（扁平，父级由 parent_id 表达）。 */
export function useUnits(projectId: string) {
    return useQuery({
        queryKey: qk.unitsRoot(projectId),
        queryFn: () => fetchAllUnits(projectId),
        enabled: Boolean(projectId),
    });
}

/**
 * 单元树的变更统一作废 unitsRoot（T3.1 后项目详情不再内嵌单元）。
 */
function useInvalidateUnits(projectId: string) {
    const client = useQueryClient();
    return () => {
        client.invalidateQueries({ queryKey: qk.unitsRoot(projectId) });
    };
}

export function useCreateUnits(projectId: string) {
    const invalidate = useInvalidateUnits(projectId);
    return useMutation({
        mutationFn: (units: UnitInput[]) => createUnits(projectId, units),
        onSuccess: invalidate,
    });
}

export function useUpdateUnit(projectId: string) {
    const invalidate = useInvalidateUnits(projectId);
    return useMutation({
        mutationFn: ({ unitId, patch }: { unitId: string; patch: Partial<CreativeUnit> }) =>
            updateUnit(projectId, unitId, patch),
        onSuccess: invalidate,
    });
}

export function useDeleteUnit(projectId: string) {
    const invalidate = useInvalidateUnits(projectId);
    return useMutation({
        mutationFn: (unitId: string) => deleteUnit(projectId, unitId),
        onSuccess: invalidate,
    });
}
