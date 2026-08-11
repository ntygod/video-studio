"use client";

import { useEffect } from "react";
import { BookMarked, MessageSquare, Pin, Save, Sparkles, UserRound } from "lucide-react";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceStore, SCRATCH_DRAFT_KEY } from "@/features/workspace/stores/use-workspace-store";
import { useUpdateProject } from "@/services/queries";
import { useIsAgentInline } from "@/shared/hooks/use-media-query";
import { Button, Form, Input, Surface, Tag, Text, Textarea, useApp } from "@/shared/ui";
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
            <div className="text-caption text-[var(--s-faint)]">{label}</div>
            <div className="mt-1 text-body leading-6 text-[var(--s-ink)]">{value || "尚未填写"}</div>
        </div>
    );
}

/** 画布 · 设定：项目简介与角色/世界/风格设定集。 */
export function BriefView() {
    const { message } = useApp();
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
        <div className="mx-auto w-full max-w-[1120px] px-5 py-6 md:px-7">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <Text as="h1" variant="heading" tone="ink">
                        创作策划
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                        定义意图、受众与边界，再建立需要长期保持一致的创作设定。
                    </Text>
                </div>
                <Button icon={<Sparkles className="size-4" />} onClick={askAgent}>
                    让 AI 补全
                </Button>
            </div>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(300px,0.8fr)]">
                <Surface as="section" level="panel" radius="md" hairline lift inset="4">
                    <div className="mb-5 flex items-start gap-3">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-action-soft)] text-[var(--s-action)]">
                            <BookMarked className="size-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                            <Text as="h2" variant="heading" tone="ink">
                                Creative Brief
                            </Text>
                            <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                                描述作品为什么存在，而不是把它锁死在固定模板里。
                            </Text>
                        </div>
                        {project.brief.approved ? <Tag color="green">已确认</Tag> : <Tag>草稿</Tag>}
                    </div>

                    <Form form={form} layout="vertical">
                        <div className="grid gap-x-4 md:grid-cols-2">
                            <Form.Item name="title" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
                                <Input />
                            </Form.Item>
                            <Form.Item name="audience" label="目标受众">
                                <Input placeholder="例如：18–35 岁悬疑科幻观众" />
                            </Form.Item>
                        </div>
                        <Form.Item name="concept" label="核心概念">
                            <Textarea rows={5} placeholder="这个作品最独特、最值得被看见的想法是什么？" />
                        </Form.Item>
                        <Form.Item name="objective" label="创作目标">
                            <Textarea rows={2} placeholder="最终要完成什么、让观众获得什么？" />
                        </Form.Item>
                        <Form.Item name="format_notes" label="形式与交付补充">
                            <Input placeholder="例如：5 集 × 8 分钟、竖屏、需要旁白" />
                        </Form.Item>

                        {project.brief.tone.length ? (
                            <div className="mb-5">
                                <div className="mb-2 text-label text-[var(--s-muted)]">语气与节奏</div>
                                <div className="flex flex-wrap gap-1.5">
                                    {project.brief.tone.map((tone) => (
                                        <Tag key={tone} color="orange" className="m-0">
                                            {tone}
                                        </Tag>
                                    ))}
                                </div>
                            </div>
                        ) : null}

                        <Button
                            variant="primary"
                            icon={<Save className="size-4" />}
                            loading={updateProject.isPending}
                            onClick={() => void save()}
                        >
                            保存 Brief
                        </Button>
                    </Form>
                </Surface>

                <aside className="space-y-4">
                    <Surface as="section" level="panel" radius="md" hairline lift inset="4">
                        <div className="flex items-center gap-2">
                            <UserRound className="size-4 text-[var(--s-muted)]" />
                            <Text as="h2" variant="heading" tone="ink" className="min-w-0 flex-1">
                                角色
                            </Text>
                            <span className="text-caption text-[var(--s-faint)]">{project.bible.characters.length} 个</span>
                        </div>
                        {project.bible.characters.length ? (
                            <div className="mt-3 divide-y divide-[var(--hairline)]">
                                {project.bible.characters.slice(0, 5).map((character) => (
                                    <div key={character.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                                        <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--r-sm)] bg-[var(--s-raised)] text-label text-[var(--s-ink)]">
                                            {character.name.charAt(0)}
                                        </span>
                                        <div className="min-w-0 flex-1">
                                            <Text as="div" variant="label" tone="ink" weight={500} truncate>
                                                {character.name}
                                            </Text>
                                            <Text variant="caption" tone="muted" truncate className="mt-0.5 block">
                                                {character.role || character.personality || "尚未填写角色定位"}
                                            </Text>
                                        </div>
                                        <Pin className="size-3.5 text-[var(--s-action)]" />
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="mt-3">
                                <EmptyState
                                    title="还没有角色设定"
                                    description="让 AI 根据 Brief 建立第一版角色。"
                                    action={
                                        <Button size="sm" icon={<MessageSquare className="size-3.5" />} onClick={askAgent}>
                                            建立角色
                                        </Button>
                                    }
                                />
                            </div>
                        )}
                    </Surface>

                    <Surface as="section" level="panel" radius="md" hairline lift inset="4">
                        <div className="flex items-center gap-2">
                            <BookMarked className="size-4 text-[var(--s-muted)]" />
                            <Text as="h2" variant="heading" tone="ink">
                                世界与风格
                            </Text>
                        </div>
                        {hasBibleContent ? (
                            <div className="mt-4 space-y-4">
                                <BibleField label="一句话简介" value={project.bible.logline} />
                                <BibleField label="整体走向" value={project.bible.long_arc} />
                                <BibleField label="世界前提" value={project.bible.world.premise} />
                                <BibleField label="画面方向" value={project.bible.style.visual_direction} />
                                {project.bible.themes.length ? (
                                    <div className="flex flex-wrap gap-1.5">
                                        {project.bible.themes.map((theme) => (
                                            <Tag key={theme} className="m-0">
                                                {theme}
                                            </Tag>
                                        ))}
                                    </div>
                                ) : null}
                            </div>
                        ) : (
                            <div className="mt-3">
                                <EmptyState
                                    title="还没有世界或风格设定"
                                    description="这些内容会在每轮创作中保持角色与画面一致。"
                                    action={
                                        <Button size="sm" icon={<MessageSquare className="size-3.5" />} onClick={askAgent}>
                                            让 AI 整理
                                        </Button>
                                    }
                                />
                            </div>
                        )}
                    </Surface>
                </aside>
            </div>
        </div>
    );
}
