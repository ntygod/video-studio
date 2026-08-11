"use client";

import { useCreateUnits } from "@/services/queries";
import { Form, Input, Modal, Select, Textarea, useApp } from "@/shared/ui";

export type UnitCreateModalProps = {
    open: boolean;
    projectId: string;
    /** 供"放入已有单元"下拉使用的选项。 */
    unitOptions: Array<{ value: string; label: string }>;
    /** 打开弹窗时预选的父单元。 */
    defaultParentId?: string | null;
    /** 新单元的排序位置。 */
    orderIndex: number;
    onClose: () => void;
    onCreated?: (unitId: string) => void;
};

type UnitFormValues = {
    title: string;
    unit_type?: string;
    parent_id?: string;
    summary?: string;
};

/** 创作单元类型的常见取值。后端接受任意文本，这里只做输入提示。 */
const UNIT_TYPE_SUGGESTIONS = ["volume", "chapter", "episode", "scene", "shot", "section", "task"].map((value) => ({
    value,
    label: { volume: "卷", chapter: "章节", episode: "分集", scene: "场景", shot: "镜头", section: "小节", task: "任务" }[value],
}));

/** 新建创作单元。unit_type 是开放文本，允许用户自造类型。 */
export function UnitCreateModal({
    open,
    projectId,
    unitOptions,
    defaultParentId,
    orderIndex,
    onClose,
    onCreated,
}: UnitCreateModalProps) {
    const { message } = useApp();
    const [form] = Form.useForm<UnitFormValues>();
    const createUnits = useCreateUnits(projectId);

    const submit = async () => {
        const values = await form.validateFields();
        try {
            const created = await createUnits.mutateAsync([
                {
                    title: values.title,
                    unit_type: values.unit_type || "unit",
                    parent_id: values.parent_id || defaultParentId || null,
                    summary: values.summary || "",
                    order_index: orderIndex,
                },
            ]);
            form.resetFields();
            onClose();
            message.success("创作单元已创建");
            if (created[0]) onCreated?.(created[0].id);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "创建失败");
        }
    };

    return (
        <Modal
            title="添加创作单元"
            open={open}
            onCancel={onClose}
            onOk={() => void submit()}
            okText="创建"
            cancelText="取消"
            confirmLoading={createUnits.isPending}
        >
            <Form form={form} layout="vertical" initialValues={{ parent_id: defaultParentId || undefined }} className="pt-2">
                <Form.Item name="title" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
                    <Input placeholder="例如：第一章、开场场景、镜头 01" />
                </Form.Item>
                <Form.Item name="unit_type" label="内容类型" extra="可以直接输入你自己的类型名">
                    <Select allowClear showSearch options={UNIT_TYPE_SUGGESTIONS} placeholder="章节、场景、镜头、任务……" />
                </Form.Item>
                <Form.Item name="parent_id" label="放入已有单元">
                    <Select allowClear showSearch optionFilterProp="label" options={unitOptions} placeholder="项目根级" />
                </Form.Item>
                <Form.Item name="summary" label="一句话说明">
                    <Textarea rows={3} placeholder="这个单元讲什么" />
                </Form.Item>
            </Form>
        </Modal>
    );
}
