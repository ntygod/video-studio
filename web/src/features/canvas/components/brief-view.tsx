"use client";

import { useEffect } from "react";
import { App, Button, Form, Input, Tag } from "antd";
import { MessageSquare, Save } from "lucide-react";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceStore, SCRATCH_DRAFT_KEY } from "@/features/workspace/stores/use-workspace-store";
import { useUpdateProject } from "@/services/queries";
import { useIsAgentInline } from "@/shared/hooks/use-media-query";
import { EmptyState } from "@/shared/ui/empty-state";

type BriefFormValues = {
    title: string;
    audience?: string;
    concept?: string;
    objective?: string;
    format_notes?: string;
};

/** 让 AI 整理设定集的开场提示。 */
const BIBLE_PROMPT = "请根据当前项目想法，帮我整理角色、世界背景和需要保持一致的设定";

function BibleField({ label, value }: { label: string; value: string }) {
    return (
        <div>
            <div className="text-[10px] text-[var(--studio-faint)]">{label}</div>
            <div className="mt-1 text-[13px] leading-6 text-[var(--studio-ink)]">{value || "尚未填写"}</div>
        </div>
    );
}

/** 画布 · 设定：项目简介与角色/世界/风格设定集。 */
export function BriefView() {
    const { message } = App.useApp();
    const [form] = Form.useForm<BriefFormValues>();
    const { projectId, project, hasBibleContent } = useWorkspaceData();
    const updateProject = useUpdateProject(projectId);

    const agentInline = useIsAgentInline();
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);
    const setComposerDraft = useWorkspaceStore((state) => state.setComposerDraft);

    useEffect(() => {
        if (!project) return;
        form.setFieldsValue({
            title: project.title,
            concept: project.brief.concept,
            objective: project.brief.objective,
            format_notes: project.brief.format_notes,
            audience: project.brief.audience.description,
        });
    }, [form, project]);

    if (!project) return null;

    const save = async () => {
        const values = await form.validateFields();
        try {
            await updateProject.mutateAsync({
                expectedRevision: project.revision,
                patch: {
                    title: values.title,
                    project_type: project.project_type,
                    workflow_id: project.workflow_id,
                    brief: {
                        ...project.brief,
                        title: values.title,
                        concept: values.concept || "",
                        objective: values.objective || "",
                        format_id: project.brief.format_id,
                        format_notes: values.format_notes || "",
                        audience: { ...project.brief.audience, description: values.audience || "" },
                    },
                },
            });
            message.success("项目信息已保存");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "保存失败");
        }
    };

    const askAgent = () => {
        // 草稿存在未选中对话的暂存位，助手面板打开后会读到它。
        setComposerDraft(SCRATCH_DRAFT_KEY, BIBLE_PROMPT);
        if (!agentInline) setAgentDrawer(true);
        else if (agentCollapsed) toggleAgent();
    };

    return (
        <div className="mx-auto w-full max-w-[900px] space-y-5 px-5 py-6 md:px-7">
            <section className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5">
                <div className="mb-5">
                    <h1 className="text-[15px] font-semibold text-[var(--studio-ink)]">你要创作什么</h1>
                    <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                        记录项目想法、面向的人，以及最终要达成的目标。
                    </p>
                </div>

                <Form form={form} layout="vertical">
                    <div className="grid gap-4 md:grid-cols-2">
                        <Form.Item name="title" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
                            <Input />
                        </Form.Item>
                        <Form.Item name="audience" label="目标受众">
                            <Input placeholder="例如：第一次接触这个主题的人" />
                        </Form.Item>
                    </div>
                    <Form.Item name="concept" label="想法">
                        <Input.TextArea rows={4} placeholder="你想让观众、读者或听众看到什么？" />
                    </Form.Item>
                    <Form.Item name="objective" label="这次创作要达成什么">
                        <Input.TextArea rows={2} placeholder="例如：建立世界观、讲清一个观点，或完成一支可发布的视频" />
                    </Form.Item>
                    <Form.Item name="format_notes" label="形式补充">
                        <Input placeholder="例如：横屏、系列化、需要旁白" />
                    </Form.Item>
                    <Button
                        type="primary"
                        icon={<Save className="size-4" />}
                        loading={updateProject.isPending}
                        onClick={() => void save()}
                    >
                        保存项目信息
                    </Button>
                </Form>
            </section>

            <section className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-5">
                <div className="mb-4">
                    <h2 className="text-[15px] font-semibold text-[var(--studio-ink)]">角色与世界</h2>
                    <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                        需要在整个项目中保持一致的人物、地点、规则和风格。长篇创作靠它防止人设走样。
                    </p>
                </div>

                {hasBibleContent ? (
                    <div className="grid gap-4 md:grid-cols-2">
                        <BibleField label="一句话简介" value={project.bible.logline} />
                        <BibleField label="整体走向" value={project.bible.long_arc} />
                        <div>
                            <div className="text-[10px] text-[var(--studio-faint)]">主题</div>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                                {project.bible.themes.length ? (
                                    project.bible.themes.map((theme) => (
                                        <Tag key={theme} className="m-0">
                                            {theme}
                                        </Tag>
                                    ))
                                ) : (
                                    <span className="text-[13px] text-[var(--studio-faint)]">尚未填写</span>
                                )}
                            </div>
                        </div>
                        <BibleField label="画面方向" value={project.bible.style.visual_direction} />

                        {project.bible.characters.length ? (
                            <div className="md:col-span-2">
                                <div className="text-[10px] text-[var(--studio-faint)]">角色</div>
                                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                    {project.bible.characters.map((character) => (
                                        <div
                                            key={character.id}
                                            className="rounded-md border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] p-3"
                                        >
                                            <div className="text-[13px] font-medium text-[var(--studio-ink)]">{character.name}</div>
                                            <div className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                                                {character.role || character.personality || "尚未填写角色定位"}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ) : null}
                    </div>
                ) : (
                    <EmptyState
                        title="还没有角色或世界设定"
                        description="让 AI 根据你的想法整理一版，之后可以随时调整。"
                        action={
                            <Button type="primary" icon={<MessageSquare className="size-4" />} onClick={askAgent}>
                                让 AI 帮我整理
                            </Button>
                        }
                    />
                )}
            </section>
        </div>
    );
}
