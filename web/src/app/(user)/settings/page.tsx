"use client";

import { useMemo, useState } from "react";
import { AudioWaveform, BrainCircuit, ImageIcon, Plus, RotateCw, SquarePen, Trash2, Video } from "lucide-react";

import { ProviderFormModal } from "@/features/settings/components/provider-form-modal";
import { formatModelPricing } from "@/features/settings/lib/model-pricing";
import { capabilityLabel } from "@/features/workspace/lib/labels";
import type { ModelCapability, ProviderProfile } from "@/services/api";
import {
    useDeleteProviderProfile,
    useModelCapabilities,
    useProviderProfiles,
    useTestProviderProfile,
    useUpdateProviderProfile,
} from "@/services/queries";
import { Button, Popconfirm, Spin, Surface, Switch, Table, Tag, Text, useApp } from "@/shared/ui";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

/** 工作台真正依赖的能力，缺失时应该显眼地提示。 */
const CORE_CAPABILITIES = ["llm", "image", "video", "tts"];

function capabilityIcon(type: string) {
    if (type === "llm") return <BrainCircuit className="size-4" />;
    if (type === "image") return <ImageIcon className="size-4" />;
    if (type === "video") return <Video className="size-4" />;
    return <AudioWaveform className="size-4" />;
}

function ProviderCard({
    provider,
    onEdit,
    onDelete,
    onToggle,
    onTest,
    testing,
}: {
    provider: ProviderProfile;
    onEdit: () => void;
    onDelete: () => void;
    onToggle: (enabled: boolean) => void;
    onTest: () => void;
    testing: boolean;
}) {
    const pricedModels = provider.models.filter(
        (model) => model.pricing && Object.keys(model.pricing).length > 0,
    ).length;
    return (
        <Surface level="panel" radius="md" hairline lift inset="4" className="h-full">
            <div className="flex items-center justify-between gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-[var(--s-muted)]">
                    {capabilityIcon(provider.capability_type)}
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <Text as="span" variant="body" tone="ink" weight={600} truncate>
                            {provider.name}
                        </Text>
                        <Tag className="m-0">{capabilityLabel(provider.capability_type)}</Tag>
                    </div>
                    <div className="mt-1 truncate text-caption text-[var(--s-faint)]">
                        {provider.adapter} · {provider.base_url || "无 Base URL"}
                    </div>
                </div>
                <Switch size="small" checked={provider.enabled} onChange={onToggle} aria-label={`启用 ${provider.name}`} />
            </div>

            <dl className="mt-4 space-y-2 text-caption">
                <div className="flex items-center justify-between">
                    <dt className="text-[var(--s-faint)]">API Key</dt>
                    <dd className="font-mono text-[var(--s-muted)]">{provider.api_key || "未设置"}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                    <dt className="shrink-0 text-[var(--s-faint)]">模型</dt>
                    <dd className="truncate text-[var(--s-muted)]">
                        {provider.models.map((model) => model.model_id).join("、") || "未配置"}
                    </dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                    <dt className="shrink-0 text-[var(--s-faint)]">价格覆盖</dt>
                    <dd className={pricedModels === provider.models.length && pricedModels > 0 ? "text-[var(--s-success)]" : "text-[var(--s-warning)]"}>
                        {pricedModels}/{provider.models.length} 个模型已定价
                    </dd>
                </div>
            </dl>
            <div className="mt-4 flex flex-wrap gap-2 border-t border-[var(--hairline)] pt-3">
                <Button size="sm" loading={testing} onClick={onTest}>
                    连接测试
                </Button>
                <Button size="sm" icon={<SquarePen className="size-3.5" />} onClick={onEdit}>
                    编辑
                </Button>
                <Popconfirm title="删除此渠道？" okText="删除" cancelText="取消" onConfirm={onDelete}>
                    <Button variant="ghost" size="sm" danger aria-label="删除渠道" icon={<Trash2 className="size-3.5" />} />
                </Popconfirm>
                <Tag color={provider.enabled ? "green" : "default"} className="ml-auto self-center">
                    {provider.enabled ? "启用" : "停用"}
                </Tag>
            </div>
        </Surface>
    );
}

/** 模型与渠道配置。 */
export default function SettingsPage() {
    const { message } = useApp();
    const [modalOpen, setModalOpen] = useState(false);
    const [editing, setEditing] = useState<ProviderProfile | null>(null);

    const providersQuery = useProviderProfiles();
    const capabilitiesQuery = useModelCapabilities();
    const updateProvider = useUpdateProviderProfile();
    const deleteProvider = useDeleteProviderProfile();
    const testProvider = useTestProviderProfile();

    const providers = useMemo(() => providersQuery.data || [], [providersQuery.data]);
    const capabilities = useMemo(() => capabilitiesQuery.data || [], [capabilitiesQuery.data]);

    const missing = useMemo(
        () => CORE_CAPABILITIES.filter((type) => !capabilities.some((item) => item.capability_type === type && item.enabled)),
        [capabilities],
    );

    const openCreate = () => {
        setEditing(null);
        setModalOpen(true);
    };

    const openEdit = (provider: ProviderProfile) => {
        setEditing(provider);
        setModalOpen(true);
    };

    const remove = async (id: string) => {
        try {
            await deleteProvider.mutateAsync(id);
            message.success("渠道已删除");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    const toggle = async (provider: ProviderProfile, enabled: boolean) => {
        try {
            await updateProvider.mutateAsync({ id: provider.id, input: { enabled } });
        } catch (error) {
            message.error(error instanceof Error ? error.message : "切换失败");
        }
    };

    const test = async (provider: ProviderProfile) => {
        try {
            const result = await testProvider.mutateAsync(provider.id);
            if (result.ok) {
                message.success(`连接正常（${result.latency_ms}ms）`);
            } else {
                message.error(`连接失败：${result.detail || "未知错误"}`);
            }
        } catch (error) {
            message.error(error instanceof Error ? error.message : "连接测试失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1280px] px-5 py-7 md:px-8 md:py-8">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--hairline)] pb-5">
                <div>
                    <Text as="h1" variant="title" tone="ink">
                        模型与渠道
                    </Text>
                    <Text as="p" variant="body" tone="muted" className="mt-1">
                        配置外部 API、模型价格与默认能力；密钥只回显掩码。
                    </Text>
                </div>
                <div className="flex gap-2">
                    <Button icon={<RotateCw className="size-4" />} onClick={() => void providersQuery.refetch()}>
                        刷新
                    </Button>
                    <Button variant="primary" icon={<Plus className="size-4" />} onClick={openCreate}>
                        新建渠道
                    </Button>
                </div>
            </header>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {CORE_CAPABILITIES.map((type) => {
                    const models = capabilities.filter((item) => item.capability_type === type && item.enabled);
                    const defaultModel = models.find((item) => item.is_default)?.model_id || models[0]?.model_id;
                    return (
                        <Surface key={type} level="panel" radius="md" hairline lift inset="4">
                            <div className="flex items-center gap-2 text-[var(--s-muted)]">
                                {capabilityIcon(type)}
                                <Text variant="label" tone="ink" className="min-w-0 flex-1">
                                    {capabilityLabel(type)}
                                </Text>
                                <span className={`size-1.5 rounded-full ${models.length ? "bg-[var(--s-success)]" : "bg-[var(--s-danger)]"}`} />
                            </div>
                            <Text as="div" variant="heading" tone="ink" className="mt-4">
                                {models.length} 个模型
                            </Text>
                            <Text variant="caption" tone="faint" truncate className="mt-1 block">
                                {defaultModel ? `默认：${defaultModel}` : "尚未配置可用模型"}
                            </Text>
                        </Surface>
                    );
                })}
            </div>

            {missing.length ? (
                <Surface level="raised" radius="md" hairline inset="3" className="mt-5">
                    <Text variant="label" tone="muted">
                    尚未配置的能力：
                    {missing.map((type) => (
                        <Tag key={type} className="ml-1.5">
                            {capabilityLabel(type)}
                        </Tag>
                    ))}
                    <span className="ml-1">配置后工作台对应的功能才会开放。</span>
                    </Text>
                </Surface>
            ) : null}

            <div className="mt-7 flex items-end justify-between gap-3">
                <div>
                    <Text as="h2" variant="heading" tone="ink">
                        已配置渠道
                    </Text>
                    <Text variant="caption" tone="faint" className="mt-1 block">
                        模型价格会在调用前冻结，历史费用不会被后续改价重写。
                    </Text>
                </div>
                {!missing.length ? <Tag color="green">核心能力已覆盖</Tag> : null}
            </div>

            {providersQuery.error ? (
                <ErrorPanel
                    title="配置加载失败"
                    message={providersQuery.error.message}
                    onRetry={() => void providersQuery.refetch()}
                />
            ) : providersQuery.isLoading && !providers.length ? (
                <div className="flex justify-center py-20">
                    <Spin size="large" />
                </div>
            ) : providers.length === 0 ? (
                <EmptyState
                    title="还没有配置任何渠道"
                    description="至少配置一个文本模型，AI 创作助手才能工作。"
                    action={
                        <Button variant="primary" icon={<Plus className="size-4" />} onClick={openCreate}>
                            新建渠道
                        </Button>
                    }
                />
            ) : (
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    {providers.map((provider) => (
                        <ProviderCard
                            key={provider.id}
                            provider={provider}
                            onEdit={() => openEdit(provider)}
                            onDelete={() => void remove(provider.id)}
                            onToggle={(enabled) => void toggle(provider, enabled)}
                            onTest={() => void test(provider)}
                            testing={testProvider.isPending && testProvider.variables === provider.id}
                        />
                    ))}
                </div>
            )}

            <section className="mt-8">
                <Text as="h2" variant="heading" tone="ink" className="mb-2 block">
                    模型能力与价格
                </Text>
                <Surface level="panel" radius="md" className="overflow-hidden">
                    <Table<ModelCapability>
                        rowKey={(row) => `${row.provider_profile_id}:${row.model_id}`}
                        size="small"
                        pagination={{ pageSize: 8, hideOnSinglePage: true }}
                        dataSource={capabilities}
                        locale={{ emptyText: "暂无模型" }}
                        columns={[
                            {
                                title: "模型",
                                dataIndex: "model_id",
                                render: (value: string) => <span className="font-mono text-label">{value}</span>,
                            },
                            {
                                title: "能力",
                                dataIndex: "capability_type",
                                render: (value: string) => <Tag className="m-0">{capabilityLabel(value)}</Tag>,
                            },
                            { title: "渠道", dataIndex: "provider_name" },
                            {
                                title: "价格",
                                render: (_, row) => (
                                    <span className={row.pricing && Object.keys(row.pricing).length ? "text-[var(--s-muted)]" : "text-[var(--s-warning)]"}>
                                        {formatModelPricing(row.pricing)}
                                    </span>
                                ),
                            },
                            { title: "适配器", dataIndex: "adapter" },
                            {
                                title: "状态",
                                dataIndex: "enabled",
                                render: (value: boolean) => (
                                    <Tag color={value ? "green" : "default"} className="m-0">
                                        {value ? "启用" : "停用"}
                                    </Tag>
                                ),
                            },
                            {
                                title: "默认",
                                dataIndex: "is_default",
                                width: 90,
                                render: (value: boolean) =>
                                    value ? (
                                        <Tag color="blue" className="m-0">
                                            默认
                                        </Tag>
                                    ) : null,
                            },
                        ]}
                    />
                </Surface>
            </section>

            <ProviderFormModal open={modalOpen} provider={editing} onClose={() => setModalOpen(false)} />
        </div>
    );
}
