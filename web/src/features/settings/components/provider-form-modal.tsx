"use client";

import { useEffect } from "react";
import { App, Form, Input, Modal, Select, Switch } from "antd";
import { KeyRound } from "lucide-react";

import { capabilityLabel } from "@/features/workspace/lib/labels";
import type { ProviderProfile } from "@/services/api";
import { useCreateProviderProfile, useUpdateProviderProfile } from "@/services/queries";

const CAPABILITY_OPTIONS = ["llm", "image", "video", "tts", "audio", "embedding", "text", "other"];
const ADAPTER_OPTIONS = ["openai", "anthropic", "grok2api", "edge", "custom"];

const EMPTY_MODELS_JSON = JSON.stringify(
    [{ name: "", model_id: "", capability_type: "llm", capabilities: {}, defaults: {} }],
    null,
    2,
);

type ProviderFormValues = {
    name: string;
    capability_type: string;
    adapter: string;
    base_url: string;
    api_key?: string;
    enabled: boolean;
    settings_json: string;
    models_json: string;
};

const EMPTY_FORM: ProviderFormValues = {
    name: "",
    capability_type: "llm",
    adapter: "openai",
    base_url: "",
    api_key: "",
    enabled: true,
    settings_json: "{}",
    models_json: EMPTY_MODELS_JSON,
};

function parseJson<T>(text: string, fallback: T): T | undefined {
    try {
        return JSON.parse(text || JSON.stringify(fallback)) as T;
    } catch {
        return undefined;
    }
}

/**
 * 渠道配置弹窗。
 *
 * @param provider ProviderProfile | null 传入表示编辑，null 表示新建
 */
export function ProviderFormModal({
    open,
    provider,
    onClose,
}: {
    open: boolean;
    provider: ProviderProfile | null;
    onClose: () => void;
}) {
    const { message } = App.useApp();
    const [form] = Form.useForm<ProviderFormValues>();
    const createProvider = useCreateProviderProfile();
    const updateProvider = useUpdateProviderProfile();

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
                models_json: JSON.stringify(provider.models || [], null, 2),
            });
        } else {
            form.setFieldsValue(EMPTY_FORM);
        }
    }, [form, open, provider]);

    const save = async () => {
        const values = await form.validateFields();

        const settings = parseJson<Record<string, unknown>>(values.settings_json, {});
        if (!settings) {
            message.error("渠道设置 JSON 格式不正确");
            return;
        }

        const base = {
            name: values.name,
            capability_type: values.capability_type,
            adapter: values.adapter,
            base_url: values.base_url,
            enabled: values.enabled,
            settings,
            ...(values.api_key ? { api_key: values.api_key } : {}),
        };

        try {
            if (provider) {
                // 后端 ProviderPatch 不接受 models，编辑时模型列表只读。
                await updateProvider.mutateAsync({ id: provider.id, input: base });
                message.success("渠道已更新");
            } else {
                const models = parseJson<Array<Record<string, unknown>>>(values.models_json, []);
                if (!models) {
                    message.error("模型列表 JSON 格式不正确");
                    return;
                }
                await createProvider.mutateAsync({
                    ...base,
                    models: models.map((item) => ({
                        id: "",
                        name: String(item.name || item.model_id || ""),
                        model_id: String(item.model_id || ""),
                        capability_type: String(item.capability_type || values.capability_type),
                        capabilities: (item.capabilities as Record<string, unknown>) || {},
                        defaults: (item.defaults as Record<string, unknown>) || {},
                    })),
                });
                message.success("渠道已创建");
            }
            onClose();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "保存失败");
        }
    };

    return (
        <Modal
            title={isEdit ? "编辑渠道" : "新建渠道"}
            open={open}
            onCancel={onClose}
            onOk={() => void save()}
            okText="保存"
            cancelText="取消"
            confirmLoading={createProvider.isPending || updateProvider.isPending}
            width={640}
            forceRender
        >
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
                <Form.Item name="base_url" label="Base URL">
                    <Input placeholder="http://host:port/v1 或 http://host:port" />
                </Form.Item>
                <Form.Item name="api_key" label={isEdit ? "API Key（留空表示不修改）" : "API Key"}>
                    <Input.Password
                        prefix={<KeyRound className="size-3.5 text-[var(--studio-faint)]" />}
                        placeholder="sk-..."
                        autoComplete="new-password"
                    />
                </Form.Item>
                <Form.Item name="settings_json" label="渠道设置（JSON）">
                    <Input.TextArea rows={3} spellCheck={false} className="font-mono !text-[12px]" />
                </Form.Item>
                <Form.Item
                    name="models_json"
                    label="模型列表（JSON）"
                    extra={
                        isEdit
                            ? "后端暂不支持修改已有渠道的模型列表，这里只作查看。需要调整请删除后重建渠道。"
                            : "每个模型至少要填 model_id。"
                    }
                >
                    <Input.TextArea rows={5} readOnly={isEdit} spellCheck={false} className="font-mono !text-[12px]" />
                </Form.Item>
            </Form>
        </Modal>
    );
}
