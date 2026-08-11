"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createProviderProfile, deleteProviderProfile, discoverProviderModels, getModelCapabilities, hasCapability, listProviderProfiles, testProviderProfile, updateProviderProfile, type ModelCapability, type ProviderProfile } from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useProviderProfiles() {
    return useQuery({ queryKey: qk.providers(), queryFn: listProviderProfiles });
}

/** 模型能力清单。工作台多处依赖它判断某种能力是否可用，缓存久一点。 */
export function useModelCapabilities() {
    return useQuery({
        queryKey: qk.capabilities(),
        queryFn: getModelCapabilities,
        staleTime: 5 * 60_000,
    });
}

/** 是否已配置可用的文本模型——没有它 Agent 无法工作。 */
export function useHasLlm(): boolean {
    const { data } = useModelCapabilities();
    return hasCapability(data || [], "llm");
}

function useProviderMutation<TInput>(action: (input: TInput) => Promise<unknown>) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: action,
        onSuccess: () => {
            client.invalidateQueries({ queryKey: qk.providers() });
            client.invalidateQueries({ queryKey: qk.capabilities() });
        },
    });
}

export function useCreateProviderProfile() {
    return useProviderMutation((input: Partial<ProviderProfile>) => createProviderProfile(input));
}

export function useUpdateProviderProfile() {
    return useProviderMutation(({ id, input }: { id: string; input: Partial<ProviderProfile> }) => updateProviderProfile(id, input));
}

export function useDeleteProviderProfile() {
    return useProviderMutation((id: string) => deleteProviderProfile(id));
}

/** 从尚未保存或已保存的渠道配置中读取上游真实模型列表。 */
export function useDiscoverProviderModels() {
    return useMutation({ mutationFn: discoverProviderModels });
}

/** 连接测试（不写缓存，调用方自行展示结果）。 */
export function useTestProviderProfile() {
    return useMutation({ mutationFn: testProviderProfile });
}

/** 按能力类型分组，供设置页以"能力优先"的方式展示。 */
export function groupByCapability(capabilities: ModelCapability[]): Map<string, ModelCapability[]> {
    const groups = new Map<string, ModelCapability[]>();
    capabilities.forEach((item) => {
        const list = groups.get(item.capability_type) || [];
        list.push(item);
        groups.set(item.capability_type, list);
    });
    return groups;
}
