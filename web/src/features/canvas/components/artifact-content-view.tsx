import type { ReactNode } from "react";

/** 常见字段的中文名。未知字段回落为把下划线替换成空格的原名。 */
const FIELD_LABELS: Record<string, string> = {
    title: "标题",
    name: "名称",
    summary: "摘要",
    description: "说明",
    concept: "核心想法",
    objective: "创作目标",
    logline: "一句话故事",
    themes: "主题",
    long_arc: "整体走向",
    characters: "角色",
    world: "世界设定",
    premise: "背景",
    era: "时代",
    locations: "地点",
    rules: "规则",
    style: "风格",
    visual_direction: "画面方向",
    color_palette: "色彩",
    lighting: "光线",
    camera_language: "镜头语言",
    subtitle_style: "字幕风格",
    sound_direction: "声音方向",
    negative_prompts: "需要避免",
    role: "角色定位",
    personality: "性格",
    appearance: "外观",
    wardrobe: "服装",
    script: "脚本",
    narration: "旁白",
    dialogue: "对白",
    scenes: "场景",
    shots: "镜头",
    decisions: "剪辑决定",
    rationale: "理由",
    audience: "目标受众",
    format_notes: "形式说明",
    tone: "语气",
    references: "参考",
    constraints: "限制",
};

function fieldLabel(key: string) {
    return FIELD_LABELS[key] || key.replaceAll("_", " ");
}

function isEmpty(value: unknown): boolean {
    if (value == null || value === "") return true;
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length === 0;
    return false;
}

function Scalar({ value }: { value: string | number | boolean }) {
    if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
    return <span className="whitespace-pre-wrap">{String(value)}</span>;
}

function Value({ value, depth = 0 }: { value: unknown; depth?: number }): ReactNode {
    if (value == null || value === "") return <span className="text-[var(--s-faint)]">暂无内容</span>;
    if (["string", "number", "boolean"].includes(typeof value)) {
        return <Scalar value={value as string | number | boolean} />;
    }
    if (Array.isArray(value)) {
        if (!value.length) return <span className="text-[var(--s-faint)]">暂无内容</span>;
        if (value.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
            return (
                <div className="flex flex-wrap gap-1.5">
                    {value.map((item, index) => (
                        <span
                            key={index}
                            className="rounded-md bg-[var(--s-raised)] px-2 py-1 text-caption text-[var(--s-muted)]"
                        >
                            <Scalar value={item as string | number | boolean} />
                        </span>
                    ))}
                </div>
            );
        }
        return (
            <div className="space-y-3">
                {value.map((item, index) => (
                    <div key={index} className="border-l-2 border-[var(--hairline)] pl-3">
                        <Value value={item} depth={depth + 1} />
                    </div>
                ))}
            </div>
        );
    }

    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => !isEmpty(item));
    if (!entries.length) return <span className="text-[var(--s-faint)]">暂无内容</span>;
    return (
        <div className={depth > 1 ? "space-y-2" : "grid gap-3 sm:grid-cols-2"}>
            {entries.map(([key, item]) => (
                <div key={key} className="min-w-0">
                    <div className="mb-1 text-caption font-medium text-[var(--s-faint)]">{fieldLabel(key)}</div>
                    <div className="text-body leading-6 text-[var(--s-ink)]">
                        <Value value={item} depth={depth + 1} />
                    </div>
                </div>
            ))}
        </div>
    );
}

/**
 * 结构化稿件的通用渲染。
 * <p>
 * 这是所有 artifact 类型的兜底渲染方式。P2 会为 outline / script / shot_plan 等
 * 常见体裁提供专门的渲染器，让剧本长得像剧本；本组件届时退为未知类型的回落。
 */
export function ArtifactContentView({ payload }: { payload: Record<string, unknown> }) {
    const entries = Object.entries(payload).filter(([, value]) => !isEmpty(value));
    if (!entries.length) {
        return <div className="py-10 text-center text-body text-[var(--s-faint)]">这份稿件还没有内容</div>;
    }

    return (
        <div className="divide-y divide-[var(--hairline)]">
            {entries.map(([key, value]) => (
                <section key={key} className="py-4 first:pt-0 last:pb-0">
                    <h4 className="mb-2 text-caption font-semibold text-[var(--s-muted)]">{fieldLabel(key)}</h4>
                    <div className="text-body leading-6 text-[var(--s-ink)]">
                        <Value value={value} />
                    </div>
                </section>
            ))}
        </div>
    );
}
