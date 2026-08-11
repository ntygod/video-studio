"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    deleteAsset,
    listAssets,
    updateAsset,
    uploadAsset,
    type Asset,
    type UploadAssetInput,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useAssets(projectId: string, unitId?: string | null) {
    return useQuery({
        queryKey: qk.assets(projectId, unitId),
        queryFn: () => listAssets(projectId, unitId || undefined),
        enabled: Boolean(projectId),
    });
}

export function useUploadAsset(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (input: UploadAssetInput) => uploadAsset(projectId, input),
        onSuccess: () => client.invalidateQueries({ queryKey: qk.assetsRoot(projectId) }),
    });
}

/**
 * 删除素材。
 * <p>
 * 乐观地从当前单元与项目两个作用域的列表里移除，失败时回滚。
 */
/** 把素材归属到某个单元/镜头（素材库拖到分镜卡）。 */
export function useUpdateAsset(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({ assetId, unitId }: { assetId: string; unitId: string }) =>
            updateAsset(assetId, { unit_id: unitId }),
        onSuccess: () => client.invalidateQueries({ queryKey: qk.assetsRoot(projectId) }),
    });
}

export function useDeleteAsset(projectId: string, unitId?: string | null) {
    const client = useQueryClient();
    const key = qk.assets(projectId, unitId);

    return useMutation({
        mutationFn: (assetId: string) => deleteAsset(assetId),
        onMutate: async (assetId) => {
            await client.cancelQueries({ queryKey: key });
            const previous = client.getQueryData<Asset[]>(key);
            client.setQueryData<Asset[]>(key, (items) => (items || []).filter((item) => item.id !== assetId));
            return { previous };
        },
        onError: (_error, _assetId, context) => {
            if (context?.previous) client.setQueryData(key, context.previous);
        },
        onSettled: () => client.invalidateQueries({ queryKey: qk.assetsRoot(projectId) }),
    });
}
