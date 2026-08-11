"use client";

import { ArrowRight, Check, Clapperboard, FilePlus2, Images, MessageCircle, Plus, Settings2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import { hasContentArtifact } from "@/features/workspace/lib/labels";
import { useHasLlm } from "@/services/queries";
import { useIsAgentInline } from "@/shared/hooks/use-media-query";
import { cn } from "@/shared/lib/utils";
import { Button, Text } from "@/shared/ui";

type NextStep = {
    title: string;
    description: string;
    label: string;
    icon: typeof MessageCircle;
    onClick?: () => void;
    href?: string;
};

/**
 * 创作进度与下一步建议。
 * <p>
 * 开放模型下用户很容易不知道该做什么，这里给出一条明确的路径：
 * 配置模型 → 明确方向 → 组织结构 → 形成稿件 → 补充素材 → 生成成片。
 */
export function GettingStartedPanel({ onCreateUnit }: { onCreateUnit: () => void }) {
    const router = useRouter();
    const { project, units, artifacts, assets } = useWorkspaceData();
    const { hrefFor } = useWorkspaceRoute();
    const hasLlm = useHasLlm();

    const agentInline = useIsAgentInline();
    const agentCollapsed = useWorkspaceStore((state) => state.agentCollapsed);
    const toggleAgent = useWorkspaceStore((state) => state.toggleAgent);
    const setAgentDrawer = useWorkspaceStore((state) => state.setAgentDrawer);

    const openAgent = () => {
        if (!agentInline) setAgentDrawer(true);
        else if (agentCollapsed) toggleAgent();
    };

    if (!project) return null;

    const directionDone = Boolean(project.brief.concept.trim() && project.brief.objective.trim());
    const structureDone = units.length > 0;
    const contentDone = hasContentArtifact(artifacts);
    const assetsDone = assets.length > 0;

    const steps = [
        { label: "明确方向", detail: "想法、目标和受众", done: directionDone, icon: MessageCircle },
        { label: "组织内容", detail: "章节、场景或任意单元", done: structureDone, icon: Plus },
        { label: "形成稿件", detail: "采纳 AI 建议并保存版本", done: contentDone, icon: FilePlus2 },
        { label: "补充素材", detail: "图片、视频、音频或文档", done: assetsDone, icon: Images },
    ];

    const next: NextStep = !hasLlm
        ? {
              title: "先配置一个 AI 模型",
              description: "配置完成后，工作台就能帮你梳理方向和生成内容。",
              label: "去配置模型",
              icon: Settings2,
              href: "/settings",
          }
        : !directionDone
          ? {
                title: "先把想法说清楚",
                description: "告诉 AI 你要创作什么，它会从目标、受众和结构开始提问。",
                label: "和 AI 梳理方向",
                icon: MessageCircle,
                onClick: openAgent,
            }
          : !structureDone
            ? {
                  title: "建立第一个内容单元",
                  description: "可以是章节、场景、镜头，也可以是你自己定义的节点。",
                  label: "创建内容单元",
                  icon: Plus,
                  onClick: onCreateUnit,
              }
            : !contentDone
              ? {
                    title: "继续完善第一版内容",
                    description: "在对话中提出要求，采纳建议后会保存新的版本。",
                    label: "继续创作",
                    icon: MessageCircle,
                    onClick: openAgent,
                }
              : !assetsDone
                ? {
                      title: "补充参考素材",
                      description: "上传图片、视频、音频或文档，让创作更具体。",
                      label: "添加素材",
                      icon: Images,
                      href: hrefFor("media"),
                  }
                : {
                      title: "准备生成成片",
                      description: "内容和素材已经就位，先检查制作条件，再生成成片。",
                      label: "查看生成状态",
                      icon: Clapperboard,
                      href: hrefFor("produce"),
                  };

    const NextIcon = next.icon;
    const actionButton = (
        <Button variant="primary" icon={<NextIcon className="size-4" />} onClick={next.onClick ?? (() => router.push(next.href as string))}>
            {next.label}
        </Button>
    );

    return (
        <section className="overflow-hidden rounded-[var(--r-md)] bg-[var(--s-panel)] shadow-[var(--lift)]">
            <div className="grid lg:grid-cols-[minmax(0,1.15fr)_minmax(260px,0.85fr)]">
                <div className="p-5 md:p-6">
                    <div className="flex items-center gap-2 text-caption font-semibold text-[var(--s-muted)]">
                        <Sparkles className="size-4 text-[var(--s-faint)]" />
                        建议下一步
                    </div>
                    <Text as="h2" variant="title" tone="ink" className="mt-3">
                        {next.title}
                    </Text>
                    <Text as="p" variant="body" tone="muted" className="mt-2 max-w-xl leading-6">
                        {next.description}
                    </Text>
                    <div className="mt-5 flex flex-wrap gap-2">
                        {actionButton}
                        {!directionDone && hasLlm ? (
                            <Link href={hrefFor("brief")}>
                                <Button icon={<ArrowRight className="size-4" />}>自己填写设定</Button>
                            </Link>
                        ) : null}
                    </div>
                </div>

                <div className="border-t border-[var(--hairline)] bg-[var(--s-raised)] p-5 lg:border-l lg:border-t-0">
                    <div className="text-caption font-semibold text-[var(--s-muted)]">创作进度</div>
                    <ol className="mt-4 space-y-3">
                        {steps.map((step) => {
                            const StepIcon = step.icon;
                            return (
                                <li key={step.label} className="flex items-center gap-3">
                                    <span
                                        className={cn(
                                            "flex size-7 shrink-0 items-center justify-center rounded-full border",
                                            step.done ? "border-[var(--s-ink)] bg-[var(--s-ink)] text-[var(--s-base)]" : "border-[var(--hairline-strong)] text-[var(--s-faint)]",
                                        )}
                                    >
                                        {step.done ? <Check className="size-3.5" /> : <StepIcon className="size-3.5" />}
                                    </span>
                                    <div className="min-w-0">
                                        <div className={cn("text-body", step.done ? "text-[var(--s-ink)]" : "text-[var(--s-muted)]")}>{step.label}</div>
                                        <div className="truncate text-caption text-[var(--s-faint)]">{step.detail}</div>
                                    </div>
                                </li>
                            );
                        })}
                    </ol>
                </div>
            </div>
        </section>
    );
}
