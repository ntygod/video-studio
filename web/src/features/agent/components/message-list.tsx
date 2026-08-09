"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ConversationMessage } from "@/services/api";
import { cn } from "@/shared/lib/utils";

/** 空对话时的开场建议。 */
const STARTER_PROMPTS = [
    "先问我几个关键问题，帮我把创作方向梳理清楚",
    "根据当前想法，给我三种不同的内容结构",
    "帮我明确目标受众，以及这次创作最重要的目标",
];

function MessageBubble({ message }: { message: ConversationMessage }) {
    const isUser = message.role === "user";
    return (
        <div className={cn("chat-msg-in", isUser ? "pl-8" : "pr-4")}>
            <div
                className={cn(
                    "rounded-lg px-3 py-2.5 text-[13px] leading-6",
                    isUser
                        ? "bg-[var(--studio-action)] text-[var(--studio-action-foreground)]"
                        : "border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] text-[var(--studio-ink)]",
                )}
            >
                {isUser ? (
                    <div className="whitespace-pre-wrap">{message.content}</div>
                ) : (
                    <div className="markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    </div>
                )}
            </div>
        </div>
    );
}

/**
 * 对话消息流。
 *
 * @param messages ConversationMessage[] 消息列表
 * @param pending boolean AI 是否正在回复
 * @param onPickPrompt (prompt: string) => void 点击开场建议
 */
export function MessageList({
    messages,
    pending,
    onPickPrompt,
}: {
    messages: ConversationMessage[];
    pending: boolean;
    onPickPrompt: (prompt: string) => void;
}) {
    const endRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, [messages.length, pending]);

    if (!messages.length && !pending) {
        return (
            <div className="flex min-h-full items-center justify-center px-4 text-center">
                <div className="max-w-[280px]">
                    <Sparkles className="mx-auto size-6 text-[var(--studio-action)]" />
                    <div className="mt-3 text-[13px] font-medium text-[var(--studio-ink)]">从一句话开始</div>
                    <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                        选一个开场，或者直接告诉 AI 你想做什么。
                    </p>
                    <div className="mt-4 space-y-2 text-left">
                        {STARTER_PROMPTS.map((prompt) => (
                            <button
                                key={prompt}
                                type="button"
                                onClick={() => onPickPrompt(prompt)}
                                className="block w-full rounded-md border border-[var(--studio-line)] bg-[var(--studio-surface-raised)] px-3 py-2 text-left text-[11px] leading-5 text-[var(--studio-muted)] transition-colors hover:border-[var(--studio-action-line)] hover:text-[var(--studio-ink)]"
                            >
                                {prompt}
                            </button>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-3" aria-live="polite" aria-busy={pending}>
            {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
            ))}
            {pending ? (
                <div className="flex items-center gap-2 pr-4 text-[11px] text-[var(--studio-muted)]">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    AI 正在整理你的想法…
                </div>
            ) : null}
            <div ref={endRef} />
        </div>
    );
}
