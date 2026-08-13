"use client";

import { useEffect, useState, type ClipboardEvent } from "react";
import { ClipboardPaste, CloudDownload, KeyRound, Plus, Trash2 } from "lucide-react";

import {
    modelPricingForm,
    pricingFromModelForm,
} from "@/features/settings/lib/model-pricing";
import { capabilityLabel } from "@/features/workspace/lib/labels";
import type { ProviderModel, ProviderProfile } from "@/services/api";
import { useCreateProviderProfile, useDiscoverProviderModels, useUpdateProviderProfile } from "@/services/queries";
import { Button, Form, Input, Modal, Password, Select, Switch, Table, Textarea, useApp } from "@/shared/ui";

const CAPABILITY_OPTIONS = ["llm", "image", "video", "tts", "audio", "embedding", "text", "other"];
const ADAPTER_OPTIONS = ["openai", "anthropic", "grok2api", "edge", "custom"];

type ProviderFormValues = {
    name: string;
    capability_type: string;
    adapter: string;
    base_url: string;
    api_key?: string;
    enabled: boolean;
    settings_json: string;
};

/** 模型列表的一行，JSON 与 USD 价格在展开区编辑。 */
type ModelRow = {
    key: string;
    name: string;
    model_id: string;
    capability_type: string;
    capabilities_json: string;
    defaults_json: string;
    inputUsdPerMillion: string;
    outputUsdPerMillion: string;
    cachedInputUsdPerMillion: string;
    requestUsd: string;
    is_default: boolean;
};

function nextKey(): string {
    return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2);
}

function emptyRow(capability = "llm"): ModelRow {
    return {
        key: nextKey(),
        name: "",
        model_id: "",
        capability_type: capability,
        capabilities_json: "{}",
        defaults_json: "{}",
        inputUsdPerMillion: "",
        outputUsdPerMillion: "",
        cachedInputUsdPerMillion: "",
        requestUsd: "",
        is_default: false,
    };
}

function rowFromModel(model: ProviderModel): ModelRow {
    return {
        key: model.id || nextKey(),
        name: model.name,
        model_id: model.model_id,
        capability_type: model.capability_type,
        capabilities_json: JSON.stringify(model.capabilities || {}, null, 2),
        defaults_json: JSON.stringify(model.defaults || {}, null, 2),
        ...modelPricingForm(model.pricing),
        is_default: model.is_default ?? false,
    };
}

function parseObjectJson(text: string): Record<string, unknown> | undefined {
    const trimmed = (text || "").trim();
    if (!trimmed) return {};
    try {
        const parsed = JSON.parse(trimmed) as unknown;
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
        return undefined;
    } catch {
        return undefined;
    }
}

function parseSettingsJson(text: string): Record<string, unknown> | undefined {
    const trimmed = (text || "").trim();
    if (!trimmed) return {};
    return parseObjectJson(trimmed);
}

/** 渠道配置弹窗：模型列表用表格增删行，价格按 USD 配置。 */
export function ProviderFormModal({ open, provider, onClose }: { open: boolean; provider: ProviderProfile | null; onClose: () => void }) {
    const { message } = useApp();
    const [form] = Form.useForm<ProviderFormValues>();
    const [rows, setRows] = useState<ModelRow[]>([]);
    const createProvider = useCreateProviderProfile();
    const updateProvider = useUpdateProviderProfile();
    const discoverModels = useDiscoverProviderModels();

    const isEdit = Boolean(provider);

    useEffect(() => {
        if (!open) return;
        if (provider) {
            form.setFieldsValue({
                name: provider.name,
                capability_type: provider.capability_type,
                adapter: provider.adapter,
                base_url: provider.base_url,
                api_key: "",
                enabled: provider.enabled,
                settings_json: JSON.stringify(provider.settings || {}, null, 2),
            });
            setRows(provider.models?.length ? provider.models.map(rowFromModel) : [emptyRow(provider.capability_type)]);
        } else {
            form.setFieldsValue({
                name: "",
                capability_type: "llm",
                adapter: "openai",
                base_url: "",
                api_key: "",
                enabled: true,
                settings_json: "{}",
            });
            setRows([emptyRow("llm")]);
        }
    }, [form, open, provider]);

    const updateRow = (key: string, patch: Partial<ModelRow>) => {
        setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
    };

    const addRow = () => {
        setRows((current) => [
            ...current,
            emptyRow(form.getFieldValue("capability_type") || "llm"),
        ]);
    };

    const removeRow = (key: string) => {
        setRows((current) => current.filter((row) => row.key !== key));
    };

    const toggleDefault = (key: string) => {
        setRows((current) => {
            const target = current.find((row) => row.key === key);
            if (!target) return current;
            if (target.is_default) {
                return current.map((row) => (row.key === key ? { ...row, is_default: false } : row));
            }
            return current.map((row) =>
                row.key === key
                    ? { ...row, is_default: true }
                    : row.capability_type === target.capability_type
                      ? { ...row, is_default: false }
                      : row,
            );
        });
    };

    const applyPastedApiKey = (value: string) => {
        const apiKey = value.trim();
        if (!apiKey) return;
        form.setFieldValue("api_key", apiKey);
        message.success("已粘贴 API Key");
    };

    const handleApiKeyPaste = (event: ClipboardEvent<HTMLInputElement>) => {
        const value = event.clipboardData.getData("text");
        if (!value) return;
        event.preventDefault();
        applyPastedApiKey(value);
    };

    const pasteApiKey = async () => {
        try {
            const value = await navigator.clipboard.readText();
            if (!value.trim()) {
                message.warning("剪贴板里没有文本");
                return;
            }
            applyPastedApiKey(value);
        } catch {
            message.warning("浏览器未授权读取剪贴板，请聚焦输入框后使用 Ctrl+V / ⌘V 粘贴");
        }
    };

    const loadModels = async () => {
        const values = form.getFieldsValue();
        if (!values.base_url?.trim()) {
            message.error("请先填写 Base URL");
            return;
        }
        const settings = parseSettingsJson(values.settings_json);
        if (!settings) {
            message.error("高级渠道参数 JSON 格式不正确");
            return;
        }
        try {
            const result = await discoverModels.mutateAsync({
                ...(provider ? { provider_id: provider.id } : {}),
                capability_type: values.capability_type || "llm",
                adapter: values.adapter || "openai",
                base_url: values.base_url.trim(),
                api_key: values.api_key || "",
                settings,
            });
            const capability = values.capability_type || "llm";
            setRows((current) => {
                const existing = new Map(current.filter((row) => row.model_id.trim()).map((row) => [row.model_id.trim(), row]));
                const discoveredIds = new Set(result.models.map((model) => model.model_id));
                const fromUpstream = result.models.map((model) => {
                    const saved = existing.get(model.model_id);
                    return saved
                        ? { ...saved, name: saved.name || model.name }
                        : {
                              ...emptyRow(model.capability_type || capability),
                              name: model.name || model.model_id,
                              model_id: model.model_id,
                          };
                });
                const manual = current.filter((row) => row.model_id.trim() && !discoveredIds.has(row.model_id.trim()));
                return [...fromUpstream, ...manual];
            });
            message.success(`已从上游读取 ${result.models.length} 个模型，可删除不需要的条目`);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "读取上游模型失败");
        }
    };

    const save = async () => {
        const values = await form.validateFields();

        const settings = parseSettingsJson(values.settings_json);
        if (!settings) {
            message.error("渠道设置 JSON 格式不正确");
            return;
        }

        const models: ProviderModel[] = [];
        for (const row of rows) {
            if (!row.model_id.trim()) continue;
            const capabilities = parseObjectJson(row.capabilities_json);
            const defaults = parseObjectJson(row.defaults_json);
            if (!capabilities) {
                message.error(`模型「${row.model_id}」的 capabilities JSON 格式不正确`);
                return;
            }
            if (!defaults) {
                message.error(`模型「${row.model_id}」的 defaults JSON 格式不正确`);
                return;
            }
            let pricing;
            try {
                pricing = pricingFromModelForm(row);
            } catch (error) {
                message.error(
                    `模型「${row.model_id}」${error instanceof Error ? error.message : "价格格式不正确"}`,
                );
                return;
            }
            models.push({
                id: "",
                name: row.name.trim() || row.model_id.trim(),
                model_id: row.model_id.trim(),
                capability_type: row.capability_type || values.capability_type,
                capabilities,
                defaults,
                pricing,
                is_default: row.is_default,
            });
        }
        if (!models.length) {
            message.error("至少配置一个模型（填 model_id 即可）");
            return;
        }

        const base = {
            name: values.name,
            capability_type: values.capability_type,
            adapter: values.adapter,
            base_url: values.base_url,
            enabled: values.enabled,
            settings,
            models,
            ...(values.api_key ? { api_key: values.api_key } : {}),
        };

        try {
            if (provider) {
                await updateProvider.mutateAsync({ id: provider.id, input: base });
                message.success("渠道已更新");
            } else {
                await createProvider.mutateAsync(base);
                message.success("渠道已创建");
            }
            onClose();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "保存失败");
        }
    };

    return (
        <Modal title={isEdit ? "编辑渠道" : "新建渠道"} open={open} onCancel={onClose} onOk={() => void save()} okText="保存" cancelText="取消" confirmLoading={createProvider.isPending || updateProvider.isPending} width={760}>
            <Form form={form} layout="vertical" className="pt-2">
                <div className="grid grid-cols-2 gap-3">
                    <Form.Item name="name" label="渠道名称" rules={[{ required: true, message: "请输入渠道名称" }]}>
                        <Input placeholder="例如 DeepSeek 官方" />
                    </Form.Item>
                    <Form.Item name="capability_type" label="能力类型" rules={[{ required: true }]}>
                        <Select options={CAPABILITY_OPTIONS.map((value) => ({ value, label: capabilityLabel(value) }))} />
                    </Form.Item>
                    <Form.Item name="adapter" label="适配器" rules={[{ required: true }]}>
                        <Select options={ADAPTER_OPTIONS.map((value) => ({ value, label: value }))} />
                    </Form.Item>
                    <Form.Item name="enabled" label="启用" valuePropName="checked">
                        <Switch />
                    </Form.Item>
                </div>
                <Form.Item name="base_url" label="Base URL" rules={[{ required: true, message: "请输入上游 Base URL" }]} extra="OpenAI 兼容服务通常填到 /v1；grok2api 可直接填写服务根地址。">
                    <Input placeholder="例如 https://api.example.com/v1 或 http://host:port" />
                </Form.Item>
                <Form.Item label={isEdit ? "API Key（留空表示不修改）" : "API Key"} extra="API Key 是敏感凭证，因此默认遮罩；可用右侧按钮或 Ctrl+V / ⌘V 粘贴，点击眼睛临时查看。">
                    <div className="flex gap-2">
                        <Form.Item name="api_key" noStyle>
                            <Password className="min-w-0 flex-1" prefix={<KeyRound className="size-3.5 text-[var(--s-faint)]" />} placeholder="sk-..." autoComplete="off" onPaste={handleApiKeyPaste} />
                        </Form.Item>
                        <Button icon={<ClipboardPaste className="size-3.5" />} onClick={() => void pasteApiKey()}>
                            粘贴
                        </Button>
                    </div>
                </Form.Item>

                <details className="mb-4 rounded-[var(--r-sm)] border border-[var(--hairline)] bg-[var(--s-raised)] px-3 py-2">
                    <summary className="cursor-pointer text-label font-medium text-[var(--s-muted)]">高级渠道参数（通常无需填写）</summary>
                    <p className="mt-2 text-caption leading-5 text-[var(--s-faint)]">
                        普通 OpenAI、grok2api 渠道保持 <code>{"{}"}</code> 即可。自定义上游可覆盖 models_path、chat_path、image_path、video_path、headers、api_key_header 或 api_key_scheme。
                    </p>
                    <Form.Item name="settings_json" label="高级参数（JSON）" className="mb-1 mt-2">
                        <Textarea rows={4} spellCheck={false} className="font-mono !text-label" placeholder={'{"models_path":"/v1/models","headers":{"X-Tenant":"demo"}}'} />
                    </Form.Item>
                </details>

                <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-label font-medium text-[var(--s-ink)]">模型列表{rows.some((row) => row.model_id.trim()) ? ` · ${rows.filter((row) => row.model_id.trim()).length}` : ""}</span>
                    <div className="flex gap-2">
                        <Button size="sm" icon={<CloudDownload className="size-3.5" />} loading={discoverModels.isPending} onClick={() => void loadModels()}>
                            从上游获取
                        </Button>
                        <Button size="sm" variant="dashed" icon={<Plus className="size-3.5" />} onClick={addRow}>
                            添加模型
                        </Button>
                    </div>
                </div>
                <Table<ModelRow>
                    rowKey="key"
                    size="small"
                    pagination={false}
                    scroll={{ y: 300 }}
                    dataSource={rows}
                    locale={{ emptyText: "还没有模型，点右上角添加" }}
                    expandable={{
                        expandedRowRender: (row) => (
                            <div className="grid grid-cols-2 gap-3 px-2 py-1">
                                <div>
                                    <div className="mb-1 text-caption text-[var(--s-faint)]">capabilities（JSON，可选）</div>
                                    <Textarea rows={3} spellCheck={false} className="font-mono !text-label" value={row.capabilities_json} onChange={(event) => updateRow(row.key, { capabilities_json: event.target.value })} />
                                </div>
                                <div>
                                    <div className="mb-1 text-caption text-[var(--s-faint)]">defaults（JSON，可选）</div>
                                    <Textarea rows={3} spellCheck={false} className="font-mono !text-label" value={row.defaults_json} onChange={(event) => updateRow(row.key, { defaults_json: event.target.value })} />
                                </div>
                                <div className="col-span-2 rounded-[var(--r-sm)] border border-[var(--hairline)] bg-[var(--s-panel)] p-3">
                                    <div className="mb-2 text-caption text-[var(--s-faint)]">价格（USD；token 价格按每 100 万 tokens）</div>
                                    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                                        <Input size="small" placeholder="输入，例如 1.25" value={row.inputUsdPerMillion} onChange={(event) => updateRow(row.key, { inputUsdPerMillion: event.target.value })} />
                                        <Input size="small" placeholder="输出，例如 5" value={row.outputUsdPerMillion} onChange={(event) => updateRow(row.key, { outputUsdPerMillion: event.target.value })} />
                                        <Input size="small" placeholder="缓存输入，可选" value={row.cachedInputUsdPerMillion} onChange={(event) => updateRow(row.key, { cachedInputUsdPerMillion: event.target.value })} />
                                        <Input size="small" placeholder="单次请求，可选" value={row.requestUsd} onChange={(event) => updateRow(row.key, { requestUsd: event.target.value })} />
                                    </div>
                                </div>
                            </div>
                        ),
                    }}
                    columns={[
                        {
                            title: "名称",
                            dataIndex: "name",
                            width: 160,
                            render: (_, row) => <Input size="small" placeholder="模型显示名" value={row.name} onChange={(event) => updateRow(row.key, { name: event.target.value })} />,
                        },
                        {
                            title: "Model ID",
                            dataIndex: "model_id",
                            render: (_, row) => <Input size="small" placeholder="gpt-4o / deepseek-chat…" className="font-mono" value={row.model_id} onChange={(event) => updateRow(row.key, { model_id: event.target.value })} />,
                        },
                        {
                            title: "能力",
                            dataIndex: "capability_type",
                            width: 140,
                            render: (_, row) => (
                                <Select
                                    size="small"
                                    className="w-full"
                                    value={row.capability_type}
                                    onChange={(value) => updateRow(row.key, { capability_type: value })}
                                    options={CAPABILITY_OPTIONS.map((value) => ({ value, label: capabilityLabel(value) }))}
                                />
                            ),
                        },
                        {
                            title: "价格",
                            width: 82,
                            render: (_, row) => (
                                <span className={row.inputUsdPerMillion || row.outputUsdPerMillion || row.requestUsd ? "text-[var(--s-success)]" : "text-[var(--s-faint)]"}>
                                    {row.inputUsdPerMillion || row.outputUsdPerMillion || row.requestUsd ? "已设置" : "未设置"}
                                </span>
                            ),
                        },
                        {
                            title: "默认",
                            dataIndex: "is_default",
                            width: 96,
                            render: (_, row) => (
                                <Button
                                    size="sm"
                                    variant={row.is_default ? "primary" : "ghost"}
                                    aria-label={row.is_default ? `取消默认 ${row.model_id || row.name || "未命名"}` : `设为默认 ${row.model_id || row.name || "未命名"}`}
                                    onClick={() => toggleDefault(row.key)}
                                >
                                    {row.is_default ? "默认" : "设为默认"}
                                </Button>
                            ),
                        },
                        {
                            title: "",
                            width: 44,
                            render: (_, row) => <Button variant="ghost" size="sm" danger aria-label={`删除模型 ${row.model_id || row.name || "未命名"}`} icon={<Trash2 className="size-3.5" />} onClick={() => removeRow(row.key)} />,
                        },
                    ]}
                />
            </Form>
        </Modal>
    );
}
