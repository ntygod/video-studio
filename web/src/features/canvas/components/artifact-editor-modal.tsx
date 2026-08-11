"use client";

import { useEffect, useState } from "react";

import type { Artifact } from "@/services/api";
import { useAddArtifactVersion } from "@/services/queries";
import { jsonText } from "@/shared/lib/format";
import { Modal, Textarea, useApp } from "@/shared/ui";

/**
 * 稿件的结构化编辑器。
 * <p>
 * 大多数创作不需要打开它——正常路径是和 AI 对话、采纳提案。这里是兜底的逃生舱口。
 * P2 会换成按体裁的可视化编辑，届时本弹窗降级为"查看源码"。
 */
export function ArtifactEditorModal({
    open,
    projectId,
    artifact,
    onClose,
}: {
    open: boolean;
    projectId: string;
    artifact: Artifact | null;
    onClose: () => void;
}) {
    const { message } = useApp();
    const [draft, setDraft] = useState("{}");
    const addVersion = useAddArtifactVersion(projectId);

    useEffect(() => {
        if (!open) return;
        setDraft(artifact?.current_version ? jsonText(artifact.current_version.payload) : "{}");
    }, [artifact, open]);

    const save = async () => {
        if (!artifact) return;
        let payload: Record<string, unknown>;
        try {
            payload = JSON.parse(draft) as Record<string, unknown>;
        } catch {
            message.error("JSON 格式不正确");
            return;
        }
        try {
            await addVersion.mutateAsync({ artifactId: artifact.id, payload, note: "用户编辑稿件" });
            message.success("已保存为新版本");
            onClose();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "保存失败");
        }
    };

    return (
        <Modal
            title={artifact ? `编辑源码：${artifact.name}` : "编辑源码"}
            open={open}
            onCancel={onClose}
            onOk={() => void save()}
            okText="保存为新版本"
            cancelText="取消"
            confirmLoading={addVersion.isPending}
            width={780}
        >
            <p className="mb-3 text-caption leading-5 text-[var(--s-muted)]">
                这里编辑的是稿件的结构化内容。保存会追加一个新版本，历史版本不会被覆盖。
            </p>
            <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                autoSize={{ minRows: 18, maxRows: 32 }}
                spellCheck={false}
                className="font-mono !text-label"
            />
        </Modal>
    );
}
