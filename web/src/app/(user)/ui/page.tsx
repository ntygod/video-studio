"use client";

import { useState, type ReactNode } from "react";
import { ArrowRight, Bell, Check, ImagePlus, Plus } from "lucide-react";

import {
    Button,
    Card,
    Checkbox,
    Chip,
    CompletionDots,
    Divider,
    EmptyState,
    Field,
    IconButton,
    Input,
    MediaFrame,
    Progress,
    ProgressRing,
    Select,
    Skeleton,
    Stack,
    StatusDot,
    Surface,
    Switch,
    Text,
    Textarea,
} from "@/shared/ui";

const block = "rounded-[var(--r-md)] bg-[var(--s-panel)] p-4 shadow-[var(--lift)]";

function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className={block}>
            <Text as="h2" variant="heading" tone="ink">
                {title}
            </Text>
            <div className="mt-3 flex flex-wrap items-start gap-3">{children}</div>
        </section>
    );
}

/**
 * shared/ui 基元预览页（docs/ui-craft.md §3 C2 验收）。
 * 暗色/浅色通过全局主题切换查看；1x/2x 缩放检查字号下限。
 */
export default function UiPreviewPage() {
    const [checked, setChecked] = useState(false);
    const [switchOn, setSwitchOn] = useState(true);
    const [progress, setProgress] = useState(0.62);

    return (
        <div className="mx-auto w-full max-w-[1000px] space-y-4 px-5 py-8 md:px-8">
            <Text as="h1" variant="display" tone="ink">
                UI 基元预览
            </Text>
            <Text as="p" variant="body" tone="muted">
                所有组件都来自 shared/ui。字号最低 caption（11px），无 10px；文字对比度 ≥ 4.5:1。
            </Text>

            <Section title="表面层级 Surface">
                {(["canvas", "base", "panel", "raised", "overlay"] as const).map((level) => (
                    <Surface key={level} level={level} radius="md" lift inset="3" className="min-w-[140px]">
                        <Text variant="label" tone="ink">
                            {level}
                        </Text>
                        <Text variant="caption" tone="faint">
                            hairline 与 lift 组合
                        </Text>
                    </Surface>
                ))}
            </Section>

            <Section title="卡片 Card">
                <Card padding="3" className="w-44">
                    <Text variant="body" tone="ink" weight={600}>
                        普通卡片
                    </Text>
                    <Text variant="caption" tone="muted" className="mt-1">
                        panel + lift，不靠边框
                    </Text>
                </Card>
                <Card interactive selected className="w-44">
                    <Text variant="body" tone="ink" weight={600}>
                        选中 + 可交互
                    </Text>
                    <Text variant="caption" tone="muted" className="mt-1">
                        左侧 2px 强调指示条
                    </Text>
                </Card>
                <Card media className="w-56">
                    <MediaFrame ratio="16 / 9">
                        <div className="flex h-full items-center justify-center text-caption text-[var(--s-faint)]">
                            媒体出血到边缘
                        </div>
                    </MediaFrame>
                    <div className="p-2.5">
                        <Text variant="body" tone="ink" weight={600}>
                            媒体卡片
                        </Text>
                    </div>
                </Card>
            </Section>

            <Section title="排版 Text">
                <Stack gap="1">
                    <Text variant="display" tone="ink">
                        显示 Display · Syne
                    </Text>
                    <Text variant="title" tone="ink">
                        标题 Title 19
                    </Text>
                    <Text variant="heading" tone="ink">
                        区块 Heading 15
                    </Text>
                    <Text variant="body" tone="default">
                        正文 Body 13.5 · 中文行高 1.65
                    </Text>
                    <Text variant="label" tone="muted">
                        次要 Label 12
                    </Text>
                    <Text variant="caption" tone="faint">
                        元信息 Caption 11
                    </Text>
                    <Text variant="mono" tone="muted">
                        mono-sm 11.5 · 0123456789 等宽数字
                    </Text>
                </Stack>
            </Section>

            <Section title="按钮 Button / IconButton">
                <Button variant="primary" icon={<ArrowRight className="size-4" />}>
                    主操作
                </Button>
                <Button variant="secondary">次级</Button>
                <Button variant="ghost">幽灵</Button>
                <Button variant="danger">危险</Button>
                <Button variant="dashed" icon={<Plus className="size-3.5" />}>
                    虚线
                </Button>
                <IconButton label="通知" icon={<Bell className="size-4" />} />
                <IconButton label="已激活" icon={<Check className="size-4" />} active />
            </Section>

            <Section title="chip / 状态 / 指示">
                <Chip tone="default">默认</Chip>
                <Chip tone="accent">强调</Chip>
                <Chip tone="success">成功</Chip>
                <Chip tone="warning">警告</Chip>
                <Chip tone="danger">危险</Chip>
                <Chip tone="info">信息</Chip>
                <Chip tone="default" removable label="可移除" onRemove={() => undefined}>
                    可移除
                </Chip>
                <div className="flex items-center gap-2">
                    <StatusDot tone="idle" />
                    <StatusDot tone="active" pulse />
                    <StatusDot tone="success" />
                    <StatusDot tone="error" />
                    <StatusDot tone="warning" />
                    <CompletionDots value={[true, false, true]} />
                </div>
            </Section>

            <Section title="进度 Progress / ProgressRing">
                <div className="flex w-full flex-col gap-3">
                    <Progress value={progress} />
                    <Progress indeterminate />
                    <div className="flex items-center gap-3">
                        <ProgressRing value={progress} size={36} />
                        <Button size="sm" onClick={() => setProgress((current) => (current >= 0.9 ? 0.1 : current + 0.1))}>
                            增加进度
                        </Button>
                    </div>
                </div>
            </Section>

            <Section title="骨架屏 Skeleton">
                <div className="w-full max-w-[320px] space-y-3">
                    <Skeleton variant="text" />
                    <Skeleton variant="media" />
                    <Skeleton variant="card" />
                </div>
            </Section>

            <Section title="媒体框 MediaFrame">
                <MediaFrame ratio="16 / 9" checkerboard className="w-56">
                    <div className="flex h-full items-center justify-center text-caption text-[var(--s-faint)]">
                        透明图垫棋盘格
                    </div>
                </MediaFrame>
                <MediaFrame ratio="1 / 1" className="w-28">
                    <div className="flex h-full items-center justify-center text-caption text-[var(--s-faint)]">
                        占位
                    </div>
                </MediaFrame>
            </Section>

            <Section title="表单 Field / Input / Select / Switch / Checkbox">
                <Stack gap="3" className="w-full max-w-[420px]">
                    <Field label="项目名称" htmlFor="ui-name" required>
                        <Input id="ui-name" placeholder="例如：夏日气泡水" />
                    </Field>
                    <Field label="类型" hint="选择一种内容类型">
                        <Select
                            defaultValue="chapter"
                            options={[
                                { value: "chapter", label: "章节" },
                                { value: "scene", label: "场景" },
                                { value: "shot", label: "镜头" },
                            ]}
                        />
                    </Field>
                    <Field label="一句话说明" error={checked ? undefined : "这是一个错误提示示例"}>
                        <Textarea rows={2} placeholder="这个单元讲什么" />
                    </Field>
                    <div className="flex items-center gap-3">
                        <Checkbox checked={checked} onChange={setChecked} label="自绘勾选框" />
                        <Switch checked={switchOn} onChange={setSwitchOn} aria-label="开关" />
                    </div>
                </Stack>
            </Section>

            <Section title="空状态 EmptyState">
                <div className="w-full">
                    <EmptyState
                        icon={<ImagePlus className="size-6" />}
                        title="还没有分镜"
                        description="让 AI 根据剧本生成一组镜头，或者自己添加。"
                        action={
                            <Button variant="primary" icon={<Plus className="size-4" />}>
                                让 AI 生成
                            </Button>
                        }
                        secondaryAction={
                            <Button variant="ghost">
                                或手动添加镜头
                            </Button>
                        }
                    />
                </div>
            </Section>

            <Divider />
            <Text variant="caption" tone="faint">
                预览页仅用于视觉验收；业务界面不引用本页。
            </Text>
        </div>
    );
}
