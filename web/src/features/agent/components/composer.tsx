"use client";

import { Button, Input, Tooltip } from "antd";
import { ArrowRight, LoaderCircle, SendHorizontal, Settings2 } from "lucide-react";
import Link from "next/link";

/**
 * 对话输入框。
 * <p>
 * Enter 发送、Shift+Enter 换行。模型未配置时把入口直接指向设置页，
 * 而不是发出去再报错。
 */
export function Composer({
    value,
    onChange,
    onSubmit,
    pending,
    hasLlm,
    scopeLabel,
}: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    pending: boolean;
    hasLlm: boolean;
    scopeLabel: string;
}) {
    const canSubmit = hasLlm && !pending && value.trim().length > 0;

    return (
        <div className="border-t border-[var(--studio-line)] p-3">
            {!hasLlm ? (
                <Link
                    href="/settings"
                    className="mb-2 flex items-center gap-2 rounded-md bg-[var(--studio-action-soft)] px-3 py-2 text-[11px] text-[var(--studio-ink)] transition-colors hover:bg-[var(--studio-surface-hover)]"
                >
                    <Settings2 className="size-3.5 shrink-0" />
                    <span className="min-w-0 flex-1">先配置一个 AI 模型</span>
                    <ArrowRight className="size-3.5 shrink-0" />
                </Link>
            ) : null}

            <div className="chat-composer-box rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] p-2">
                <Input.TextArea
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onPressEnter={(event) => {
                        if (event.shiftKey) return;
                        event.preventDefault();
                        if (canSubmit) onSubmit();
                    }}
                    placeholder="告诉 AI 你想创作什么…"
                    autoSize={{ minRows: 2, maxRows: 8 }}
                    disabled={pending}
                    variant="borderless"
                    className="chat-composer-textarea !px-1 !text-[13px]"
                />
                <div className="mt-1.5 flex items-center justify-between gap-2">
                    <span className="truncate text-[10px] text-[var(--studio-faint)]">作用于 {scopeLabel}</span>
                    <Tooltip title={canSubmit ? "发送（Enter）" : hasLlm ? "先输入内容" : "需要先配置模型"}>
                        <span>
                            <Button
                                type="primary"
                                size="small"
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
        </div>
    );
}
