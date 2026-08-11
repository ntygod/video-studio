"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";

/** 块级 AI 改写（T4.F3）：悬停浮出 ✨，点击把该块交给助手重写。 */
export function BlockActions({ text, onRewrite }: { text: string; onRewrite: (text: string) => void }) {
    const [visible, setVisible] = useState(false);
    return (
        <span
            className="group/block relative"
            onMouseEnter={() => setVisible(true)}
            onMouseLeave={() => setVisible(false)}
        >
            {visible ? (
                <button
                    type="button"
                    aria-label="用 AI 改写这段"
                    title="用 AI 改写这段"
                    onClick={() => onRewrite(text.slice(0, 800))}
                    className="absolute -left-6 top-0 flex size-5 items-center justify-center rounded-[var(--r-sm)] border border-[var(--hairline-strong)] bg-[var(--s-panel)] text-[var(--s-muted)] shadow-[var(--s-shadow-sm)] transition-transform hover:scale-110 hover:text-[var(--s-ink)]"
                >
                    <Sparkles className="size-3" />
                </button>
            ) : null}
        </span>
    );
}
