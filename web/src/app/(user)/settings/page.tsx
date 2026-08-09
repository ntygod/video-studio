"use client";

import { useMemo, useState } from "react";
import { App, Button, Popconfirm, Spin, Switch, Table, Tag } from "antd";
import { Plus, RotateCw, SquarePen, Trash2 } from "lucide-react";

import { ProviderFormModal } from "@/features/settings/components/provider-form-modal";
import { capabilityLabel } from "@/features/workspace/lib/labels";
import type { ModelCapability, ProviderProfile } from "@/services/api";
import {
    useDeleteProviderProfile,
    useModelCapabilities,
    useProviderProfiles,
    useUpdateProviderProfile,
} from "@/services/queries";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";

/** 工作台真正依赖的能力，缺失时应该显眼地提示。 */
const CORE_CAPABILITIES = ["llm", "image", "video", "tts"];

function ProviderCard({
    provider,
    onEdit,
    onDelete,
    onToggle,
}: {
    provider: ProviderProfile;
    onEdit: () => void;
    onDelete: () => void;
    onToggle: (enabled: boolean) => void;
}) {
    return (
        <div className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5">
            <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold text-[var(--studio-ink)]">{provider.name}</span>
                        <Tag color={provider.enabled ? "green" : "default"} className="m-0">
                            {provider.enabled ? "启用" : "停用"}
                        </Tag>
                    </div>
                    <div className="mt-1 truncate text-[11px] text-[var(--studio-faint)]">
                        {provider.adapter} · {provider.base_url || "无 Base URL"}
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Switch size="small" checked={provider.enabled} onChange={onToggle} aria-label={`启用 ${provider.name}`} />
                    <Button type="text" size="small" icon={<SquarePen className="size-3.5" />} onClick={onEdit}>
                        编辑
                    </Button>
                    <Popconfirm title="删除此渠道？" okText="删除" cancelText="取消" onConfirm={onDelete}>
                        <Button type="text" size="small" danger aria-label="删除渠道" icon={<Trash2 className="size-3.5" />} />
                    </Popconfirm>
                </div>
            </div>

            <dl className="mt-4 space-y-2 text-[11px]">
                <div className="flex items-center justify-between">
                    <dt className="text-[var(--studio-faint)]">API Key</dt>
                    <dd className="font-mono text-[var(--studio-muted)]">{provider.api_key || "未设置"}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                    <dt className="shrink-0 text-[var(--studio-faint)]">模型</dt>
                    <dd className="truncate text-[var(--studio-muted)]">
                        {provider.models.map((model) => model.model_id).join("、") || "未配置"}
                    </dd>
                </div>
            </dl>
        </div>
    );
}

/** 模型与渠道配置。 */
export default function SettingsPage() {
    const { message } = App.useApp();
    const [modalOpen, setModalOpen] = useState(false);
    const [editing, setEditing] = useState<ProviderProfile | null>(null);

    const providersQuery = useProviderProfiles();
    const capabilitiesQuery = useModelCapabilities();
    const updateProvider = useUpdateProviderProfile();
    const deleteProvider = useDeleteProviderProfile();

    const providers = useMemo(() => providersQuery.data || [], [providersQuery.data]);
    const capabilities = useMemo(() => capabilitiesQuery.data || [], [capabilitiesQuery.data]);

    const groups = useMemo(() => {
        const result = new Map<string, ProviderProfile[]>();
        providers.forEach((provider) => {
            const key = provider.capability_type || "other";
            const list = result.get(key) || [];
            list.push(provider);
            result.set(key, list);
        });
        return [...result.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    }, [providers]);

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

    return (
        <div className="mx-auto w-full max-w-[1100px] px-5 py-8 md:px-8">
            <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-[20px] font-semibold text-[var(--studio-ink)]">模型与渠道</h1>
                    <p className="mt-1 text-[13px] text-[var(--studio-muted)]">
                        每种能力都可以配置外部 API Key 与 Base URL，密钥只回显掩码。
                    </p>
                </div>
                <div className="flex gap-2">
                    <Button icon={<RotateCw className="size-4" />} onClick={() => void providersQuery.refetch()}>
                        刷新
                    </Button>
                    <Button type="primary" icon={<Plus className="size-4" />} onClick={openCreate}>
                        新建渠道
                    </Button>
                </div>
            </header>

            {missing.length ? (
                <div className="mb-6 rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] px-4 py-3 text-[12px] text-[var(--studio-muted)]">
                    尚未配置的能力：
                    {missing.map((type) => (
                        <Tag key={type} className="ml-1.5">
                            {capabilityLabel(type)}
                        </Tag>
                    ))}
                    <span className="ml-1">配置后工作台对应的功能才会开放。</span>
                </div>
            ) : null}

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
            ) : groups.length === 0 ? (
                <EmptyState
                    title="还没有配置任何渠道"
                    description="至少配置一个文本模型，AI 创作助手才能工作。"
                    action={
                        <Button type="primary" icon={<Plus className="size-4" />} onClick={openCreate}>
                            新建渠道
                        </Button>
                    }
                />
            ) : (
                <div className="space-y-6">
                    {groups.map(([capability, items]) => (
                        <section key={capability}>
                            <div className="mb-2 flex items-center gap-2">
                                <h2 className="text-[13px] font-semibold text-[var(--studio-ink)]">
                                    {capabilityLabel(capability)}
                                </h2>
                                <span className="text-[11px] text-[var(--studio-faint)]">{items.length} 个渠道</span>
                            </div>
                            <div className="grid gap-4 lg:grid-cols-2">
                                {items.map((provider) => (
                                    <ProviderCard
                                        key={provider.id}
                                        provider={provider}
                                        onEdit={() => openEdit(provider)}
                                        onDelete={() => void remove(provider.id)}
                                        onToggle={(enabled) => void toggle(provider, enabled)}
                                    />
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            )}

            <section className="mt-8">
                <h2 className="mb-2 text-[13px] font-semibold text-[var(--studio-ink)]">模型能力总览</h2>
                <div className="overflow-hidden rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)]">
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
                                render: (value: string) => <span className="font-mono text-[12px]">{value}</span>,
                            },
                            {
                                title: "能力",
                                dataIndex: "capability_type",
                                render: (value: string) => <Tag className="m-0">{capabilityLabel(value)}</Tag>,
                            },
                            { title: "渠道", dataIndex: "provider_name" },
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
                        ]}
                    />
                </div>
            </section>

            <ProviderFormModal open={modalOpen} provider={editing} onClose={() => setModalOpen(false)} />
        </div>
    );
}
