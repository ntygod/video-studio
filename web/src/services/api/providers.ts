"use client";

import { del, get, patch, post, seg } from "./http";
import type { ModelCapability, OkResult, ProviderProfile } from "./types";

export type ProviderTestResult = {
    ok: boolean;
    latency_ms: number;
    detail: string;
    models_seen?: string[];
};

export type DiscoveredProviderModel = {
    model_id: string;
    name: string;
    owned_by: string;
    capability_type: string;
};

export type ProviderDiscoveryInput = {
    provider_id?: string;
    capability_type: string;
    adapter: string;
    base_url: string;
    api_key?: string;
    settings?: Record<string, unknown>;
};

export type ProviderDiscoveryResult = {
    models: DiscoveredProviderModel[];
    source_url: string;
};

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

/** 使用表单中的未保存配置访问上游 /models，并返回真实模型 ID。 */
export function discoverProviderModels(input: ProviderDiscoveryInput) {
    return post<ProviderDiscoveryResult>("/api/provider-profiles/discover-models", input);
}

/** 连接测试：llm 发 1-token 请求，image/video/tts 只探活 base_url。 */
export function testProviderProfile(id: string) {
    return post<ProviderTestResult>(`/api/provider-profiles/${seg(id)}/test`);
}

/** 所有已启用渠道下可用的模型能力，按能力类型聚合展示。 */
export function getModelCapabilities() {
    return get<ModelCapability[]>("/api/model-capabilities");
}

/** 某种能力是否已经具备可用模型。 */
export function hasCapability(capabilities: ModelCapability[], type: string): boolean {
    return capabilities.some((item) => item.capability_type === type && item.enabled);
}
