import type { ProviderModelPricing } from "@/services/api";

const MICROUNITS_PER_USD = 1_000_000;

export type ModelPricingForm = {
    inputUsdPerMillion: string;
    outputUsdPerMillion: string;
    cachedInputUsdPerMillion: string;
    requestUsd: string;
};

function displayRate(value?: number): string {
    if (value === undefined || value === null) return "";
    return String(value / MICROUNITS_PER_USD);
}

export function modelPricingForm(
    pricing?: ProviderModelPricing,
): ModelPricingForm {
    return {
        inputUsdPerMillion: displayRate(
            pricing?.input_microunits_per_million_tokens,
        ),
        outputUsdPerMillion: displayRate(
            pricing?.output_microunits_per_million_tokens,
        ),
        cachedInputUsdPerMillion: displayRate(
            pricing?.cached_input_microunits_per_million_tokens,
        ),
        requestUsd: displayRate(pricing?.request_microunits),
    };
}

function parseUsd(value: string, label: string): number | undefined {
    const trimmed = value.trim();
    if (!trimmed) return undefined;
    const amount = Number(trimmed);
    if (!Number.isFinite(amount) || amount < 0) {
        throw new Error(`${label}必须是非负数字`);
    }
    return Math.round(amount * MICROUNITS_PER_USD);
}

export function pricingFromModelForm(
    form: ModelPricingForm,
): ProviderModelPricing {
    const input = parseUsd(form.inputUsdPerMillion, "输入价格");
    const output = parseUsd(form.outputUsdPerMillion, "输出价格");
    const cached = parseUsd(
        form.cachedInputUsdPerMillion,
        "缓存输入价格",
    );
    const request = parseUsd(form.requestUsd, "单次请求价格");
    if (
        input === undefined &&
        output === undefined &&
        cached === undefined &&
        request === undefined
    ) {
        return {};
    }
    return {
        currency: "USD",
        ...(input === undefined
            ? {}
            : { input_microunits_per_million_tokens: input }),
        ...(output === undefined
            ? {}
            : { output_microunits_per_million_tokens: output }),
        ...(cached === undefined
            ? {}
            : { cached_input_microunits_per_million_tokens: cached }),
        ...(request === undefined ? {} : { request_microunits: request }),
    };
}

function compactUsd(value: number): string {
    return new Intl.NumberFormat("zh-CN", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 6,
    }).format(value / MICROUNITS_PER_USD);
}

export function formatModelPricing(
    pricing?: ProviderModelPricing,
): string {
    if (!pricing || Object.keys(pricing).length === 0) return "未定价";
    const parts: string[] = [];
    if (pricing.input_microunits_per_million_tokens !== undefined) {
        parts.push(
            `输入 $${compactUsd(pricing.input_microunits_per_million_tokens)}/M`,
        );
    }
    if (pricing.output_microunits_per_million_tokens !== undefined) {
        parts.push(
            `输出 $${compactUsd(pricing.output_microunits_per_million_tokens)}/M`,
        );
    }
    if (pricing.request_microunits !== undefined) {
        parts.push(`请求 $${compactUsd(pricing.request_microunits)}`);
    }
    return parts.join(" · ") || "已配置价格";
}
