"use client";

import { del, get, patch, post, postForm, seg } from "./http";
import type { Asset, OkResult, Page } from "./types";

export function listAssetsPage(
    projectId: string,
    params: { unit_id?: string | null; kind?: string | null; limit?: number; cursor?: string | null } = {},
) {
    return get<Page<Asset>>(`/api/projects/${seg(projectId)}/assets`, params);
}

/** 素材列表（分页行走，返回全部命中项）。 */
export async function listAssets(projectId: string, unitId?: string): Promise<Asset[]> {
    const items: Asset[] = [];
    let cursor: string | null = null;
    do {
        const page = await listAssetsPage(projectId, { unit_id: unitId, limit: 200, cursor });
        items.push(...page.items);
        cursor = page.next_cursor;
    } while (cursor);
    return items;
}

export function getAsset(id: string) {
    return get<Asset>(`/api/assets/${seg(id)}`);
}

export function createAsset(projectId: string, input: Partial<Asset> & { uri: string; kind: string }) {
    return post<Asset>(`/api/projects/${seg(projectId)}/assets`, input);
}

/** 更新素材归属（素材库拖到分镜卡时把 unit_id 写过去）。 */
export function updateAsset(assetId: string, patchBody: { unit_id?: string | null; shot_id?: string | null }) {
    return patch<Asset>(`/api/assets/${seg(assetId)}`, patchBody);
}

export type UploadAssetInput = {
    file: File;
    kind: string;
    name?: string;
    unitId?: string | null;
};

export function uploadAsset(projectId: string, input: UploadAssetInput) {
    const body = new FormData();
    body.append("file", input.file);
    body.append("kind", input.kind);
    if (input.name) body.append("name", input.name);
    if (input.unitId) body.append("unit_id", input.unitId);
    return postForm<Asset>(`/api/projects/${seg(projectId)}/assets/upload`, body);
}

export function deleteAsset(id: string) {
    return del<OkResult>(`/api/assets/${seg(id)}`);
}
