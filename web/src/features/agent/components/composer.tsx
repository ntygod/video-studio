"use client";

import { ArrowRight, CircleStop, LoaderCircle, SendHorizontal, Settings2, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button, Surface, Textarea, Tooltip } from "@/shared/ui";

export type ComposerMode = "default" | "proposal";

/**
 * 对话输入框。
 * <p>
 * Enter 发送、Shift+Enter 换行。模型未配置时把入口直接指向设置页。
 * P1 增加模式切换（对话 / 提案优先）与停止按钮。
 */
export function Composer({
    value,
    onChange,
    onSubmit,
    onStop,
    pending,
    hasLlm,
    scopeLabel,
    mode,
    onModeChange,
}: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onStop?: () => void;
    pending: boolean;
    hasLlm: boolean;
    scopeLabel: string;
    mode: ComposerMode;
    onModeChange: (mode: ComposerMode) => void;
}) {
    const canSubmit = hasLlm && !pending && value.trim().length > 0;

    return (
        <div className="border-t border-[var(--hairline)] p-3">
            {!hasLlm ? (
                <Link
                    href="/settings"
                    className="mb-2 flex items-center gap-2 rounded-[var(--r-sm)] bg-[var(--s-raised)] px-3 py-2 text-caption text-[var(--s-ink)] transition-colors hover:bg-[var(--s-overlay)]"
                >
                    <Settings2 className="size-3.5 shrink-0" />
                    <span className="min-w-0 flex-1">先配置一个 AI 模型</span>
                    <ArrowRight className="size-3.5 shrink-0" />
                </Link>
            ) : null}

            <Surface level="raised" radius="md" hairline className="chat-composer-box p-2">
                <Textarea
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onPressEnter={(event) => {
                        if (event.shiftKey) return;
                        event.preventDefault();
                        if (canSubmit) onSubmit();
                    }}
                    placeholder="告诉 AI 你想创作什么…（输入 @ 引用上下文）"
                    autoSize={{ minRows: 2, maxRows: 8 }}
                    disabled={pending}
                    variant="borderless"
                    className="chat-composer-textarea !px-1 !text-body"
                />
                <div className="mt-1.5 flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <div className="flex shrink-0 rounded-full border border-[var(--hairline)] p-0.5 text-caption">
                            <button
                                type="button"
                                onClick={() => onModeChange("default")}
                                className={
                                    mode === "default"
                                        ? "rounded-full bg-[var(--s-raised)] px-2 py-0.5 text-[var(--s-ink)]"
                                        : "rounded-full px-2 py-0.5 text-[var(--s-faint)] hover:text-[var(--s-ink)]"
                                }
                            >
                                对话
                            </button>
                            <button
                                type="button"
                                onClick={() => onModeChange("proposal")}
                                className={
                                    mode === "proposal"
                                        ? "flex items-center gap-1 rounded-full bg-[var(--s-raised)] px-2 py-0.5 text-[var(--s-ink)]"
                                        : "flex items-center gap-1 rounded-full px-2 py-0.5 text-[var(--s-faint)] hover:text-[var(--s-ink)]"
                                }
                            >
                                <Sparkles className="size-2.5" />
                                提案优先
                            </button>
                        </div>
                        <span className="truncate text-caption text-[var(--s-faint)]">作用于 {scopeLabel}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                        {pending && onStop ? (
                            <Tooltip title="停止（协作式取消）">
                                <Button
                                    size="sm"
                                    danger
                                    aria-label="停止"
                                    icon={<CircleStop className="size-3.5" />}
                                    onClick={onStop}
                                />
                            </Tooltip>
                        ) : null}
                        <Tooltip title={canSubmit ? "发送（Enter）" : hasLlm ? "先输入内容" : "需要先配置模型"}>
                            <span>
                                <Button
                                    variant="primary"
                                    size="sm"
                                    aria-label="发送"
                                    disabled={!canSubmit}
                                    icon={
                                        pending ? (
                                            <LoaderCircle className="size-3.5 animate-spin" />
                                        ) : (
                                            <SendHorizontal className="size-3.5" />
                                        )
                                    }
                                    onClick={onSubmit}
                                />
                            </span>
                        </Tooltip>
                    </div>
                </div>
            </Surface>
        </div>
    );
}
