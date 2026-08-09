"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createUnits, deleteUnit, updateUnit, type CreativeUnit, type UnitInput } from "@/services/api";
import { qk } from "@/services/queries/keys";

/**
 * 单元树的变更目前都会落到项目详情里（后端 GET /projects/{id} 一次性返回全部单元），
 * 因此统一作废 project 与 units 两个作用域。BE-4 分页落地后，这里改为只动 units。
 */
function useInvalidateUnits(projectId: string) {
    const client = useQueryClient();
    return () => {
        client.invalidateQueries({ queryKey: qk.project(projectId) });
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
