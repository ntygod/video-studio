"use client";

import { BlockActions } from "./block-actions";

const FIELD_LABELS: Record<string, string> = {
    title: "标题",
    summary: "摘要",
    concept: "核心想法",
    objective: "目标",
    analysis: "分析",
    conclusion: "结论",
    notes: "备注",
    recommendations: "建议",
};

function isEmpty(value: unknown): boolean {
    if (value == null || value === "") return true;
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length === 0;
    return false;
}

/** analysis / generated 等文档流的通用渲染：字段分区 + 字符串块可改写。 */
export function DocumentRenderer({ payload, onRewrite }: { payload: Record<string, unknown>; onRewrite: (text: string) => void }) {
    const entries = Object.entries(payload).filter(([, value]) => !isEmpty(value));
    if (!entries.length) {
        return <div className="py-8 text-center text-label text-[var(--s-faint)]">这份稿件还没有内容</div>;
    }
    return (
        <div className="divide-y divide-[var(--hairline)]">
            {entries.map(([key, value]) => (
                <section key={key} className="py-4 first:pt-0 last:pb-0">
                    <h4 className="mb-2 text-caption font-semibold text-[var(--s-muted)]">
                        {FIELD_LABELS[key] || key.replaceAll("_", " ")}
                    </h4>
                    {typeof value === "string" ? (
                        <div className="group relative">
                            <BlockActions text={value} onRewrite={onRewrite} />
                            <p className="whitespace-pre-wrap text-body leading-6 text-[var(--s-ink)]">{value}</p>
                        </div>
                    ) : Array.isArray(value) ? (
                        <ul className="space-y-1.5">
                            {value.map((item, index) => (
                                <li key={index} className="group relative pl-4 text-body leading-6 text-[var(--s-text)]">
                                    <span className="absolute left-0 top-3 size-1 rounded-full bg-[var(--s-faint)]" />
                                    {typeof item === "string" ? (
                                        <>
                                            <BlockActions text={item} onRewrite={onRewrite} />
                                            {item}
                                        </>
                                    ) : (
                                        <pre className="whitespace-pre-wrap text-caption text-[var(--s-muted)]">
                                            {JSON.stringify(item, null, 2)}
                                        </pre>
                                    )}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <pre className="whitespace-pre-wrap text-caption leading-5 text-[var(--s-muted)]">
                            {JSON.stringify(value, null, 2)}
                        </pre>
                    )}
                </section>
            ))}
        </div>
    );
}
