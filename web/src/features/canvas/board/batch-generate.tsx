"use client";

import { useState } from "react";

import { useGenerateBatch } from "@/services/queries";
import { Form, Modal, Select, Textarea, useApp } from "@/shared/ui";

const CAPABILITIES = [
    { value: "image", label: "图片" },
    { value: "video", label: "视频" },
    { value: "voice", label: "配音" },
];

/** 多选后的批量生成弹窗：选能力、prompt 模板、参数。 */
export function BatchGenerateModal({
    open,
    unitIds,
    projectId,
    onClose,
}: {
    open: boolean;
    unitIds: string[];
    projectId: string;
    onClose: () => void;
}) {
    const { message } = useApp();
    const [form] = Form.useForm();
    const generateBatch = useGenerateBatch(projectId);
    const [busy, setBusy] = useState(false);

    const submit = async () => {
        if (!unitIds.length) return;
        const values = await form.validateFields();
        let params: Record<string, unknown> = {};
        if (values.params && String(values.params).trim()) {
            try {
                params = JSON.parse(values.params);
            } catch {
                message.error("参数 JSON 格式不正确");
                return;
            }
        }
        setBusy(true);
        try {
            const result = await generateBatch.mutateAsync({
                unit_ids: unitIds,
                capability: values.capability,
                prompt_template: values.prompt_template,
                params,
            });
            message.success(`已派发 ${result.child_job_ids.length} 个生成任务`);
            onClose();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "批量生成失败");
        } finally {
            setBusy(false);
        }
    };

    return (
        <Modal
            title={`批量生成（${unitIds.length} 个镜头）`}
            open={open}
            onCancel={onClose}
            onOk={() => void submit()}
            okText="开始生成"
            cancelText="取消"
            confirmLoading={busy}
            width={520}
        >
            <Form form={form} layout="vertical" initialValues={{ capability: "image", prompt_template: "根据单元摘要绘制分镜：{unit.summary}，风格 {bible.style.visual_direction}" }} className="pt-2">
                <Form.Item name="capability" label="能力" rules={[{ required: true }]}>
                    <Select options={CAPABILITIES} />
                </Form.Item>
                <Form.Item
                    name="prompt_template"
                    label="Prompt 模板"
                    rules={[{ required: true, message: "请输入模板" }]}
                    extra="支持 {unit.title} / {unit.summary} / {bible.style.visual_direction} 占位符"
                >
                    <Textarea rows={4} spellCheck={false} className="!text-label" />
                </Form.Item>
                <Form.Item name="params" label="参数（JSON，可选）">
                    <Textarea rows={2} spellCheck={false} placeholder='{"aspect_ratio": "16:9"}' className="font-mono !text-label" />
                </Form.Item>
            </Form>
        </Modal>
    );
}
