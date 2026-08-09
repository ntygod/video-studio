"use client";

import { del, get, post, postForm, seg } from "./http";
import type { Asset, OkResult } from "./types";

export function listAssets(projectId: string, unitId?: string) {
    return get<Asset[]>(`/api/projects/${seg(projectId)}/assets`, { unit_id: unitId });
}

export function getAsset(id: string) {
    return get<Asset>(`/api/assets/${seg(id)}`);
}

export function createAsset(projectId: string, input: Partial<Asset> & { uri: string; kind: string }) {
    return post<Asset>(`/api/projects/${seg(projectId)}/assets`, input);
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
