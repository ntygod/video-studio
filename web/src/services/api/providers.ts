"use client";

import { del, get, patch, post, seg } from "./http";
import type { ModelCapability, OkResult, ProviderProfile } from "./types";

export function listProviderProfiles() {
    return get<ProviderProfile[]>("/api/provider-profiles");
}

export function createProviderProfile(input: Partial<ProviderProfile>) {
    return post<ProviderProfile>("/api/provider-profiles", input);
}

export function updateProviderProfile(id: string, input: Partial<ProviderProfile>) {
    return patch<ProviderProfile>(`/api/provider-profiles/${seg(id)}`, input);
}

export function deleteProviderProfile(id: string) {
    return del<OkResult>(`/api/provider-profiles/${seg(id)}`);
}

/** 所有已启用渠道下可用的模型能力，按能力类型聚合展示。 */
export function getModelCapabilities() {
    return get<ModelCapability[]>("/api/model-capabilities");
}

/** 某种能力是否已经具备可用模型。 */
export function hasCapability(capabilities: ModelCapability[], type: string): boolean {
    return capabilities.some((item) => item.capability_type === type && item.enabled);
}
