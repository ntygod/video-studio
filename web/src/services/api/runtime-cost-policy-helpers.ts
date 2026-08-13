export type UnpricedProviderMode = "allow" | "block";

export type RuntimeCostPolicyMeta = {
    label: string;
    shortLabel: string;
    description: string;
    warning: string;
};

const META: Record<UnpricedProviderMode, RuntimeCostPolicyMeta> = {
    allow: {
        label: "尽力计价",
        shortLabel: "尽力",
        description:
            "允许未配置价格或未返回 usage 的 Provider 调用继续执行，但会将它们标记为未完整计价。",
        warning: "成本上限可能低估真实支出。",
    },
    block: {
        label: "严格计价",
        shortLabel: "严格",
        description:
            "新 Agent 回合只能调用具有明确价格配置并返回可计量 usage 的模型。",
        warning:
            "缺少价格会在请求前阻止；成功响应缺少 usage 时会留下审计记录并终止回合。",
    },
};

export function runtimeCostPolicyMeta(
    mode: UnpricedProviderMode,
): RuntimeCostPolicyMeta {
    return META[mode];
}

export function normalizeUnpricedProviderMode(
    value: unknown,
): UnpricedProviderMode {
    return value === "block" ? "block" : "allow";
}
