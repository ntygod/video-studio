"use client";

import { BlockActions } from "./block-actions";

type ScriptLine = { character?: string; name?: string; line?: string; text?: string };
type Scene = {
    heading?: string;
    scene_heading?: string;
    action?: string;
    description?: string;
    dialogue?: ScriptLine[];
    lines?: ScriptLine[];
};

function SceneBlock({ scene, onRewrite }: { scene: Scene; onRewrite: (text: string) => void }) {
    const heading = scene.heading || scene.scene_heading || "场景";
    const action = scene.action || scene.description || "";
    // AI 生成的数据里 dialogue 可能是数组，也可能是整段字符串，统一归一化。
    const rawLines = scene.dialogue ?? scene.lines;
    const lines: ScriptLine[] = Array.isArray(rawLines)
        ? rawLines.map((line) => (typeof line === "string" ? { text: line } : line))
        : typeof rawLines === "string"
          ? [{ text: rawLines }]
          : [];
    return (
        <section className="border-b border-[var(--hairline)] py-4 last:border-b-0">
            <div className="flex items-center gap-1">
                <BlockActions text={`${heading}${action ? `
${action}` : ""}`} onRewrite={onRewrite} />
                <h3 className="text-body font-semibold uppercase tracking-wide text-[var(--s-ink)]">{heading}</h3>
            </div>
            {action ? (
                <div className="group relative mt-2 pl-8">
                    <BlockActions text={action} onRewrite={onRewrite} />
                    <p className="max-w-[52ch] text-label leading-6 text-[var(--s-text)]">{action}</p>
                </div>
            ) : null}
            {lines.map((line, index) => {
                const character = line.character || line.name || "";
                const text = line.line || line.text || "";
                return (
                    <div key={index} className="mt-2 pl-12 pr-8">
                        <div className="group relative flex items-center justify-center gap-2">
                            <BlockActions text={`${character}：${text}`} onRewrite={onRewrite} />
                            <span className="text-label font-semibold text-[var(--s-ink)]">{character}</span>
                        </div>
                        <p className="mx-auto mt-0.5 max-w-[42ch] text-center text-label leading-6 text-[var(--s-text)]">{text}</p>
                    </div>
                );
            })}
        </section>
    );
}

/** 剧本渲染器：场景标题、角色名居中、对白缩进、动作正文。 */
export function ScriptRenderer({ payload, onRewrite }: { payload: Record<string, unknown>; onRewrite: (text: string) => void }) {
    const rawScenes = payload.scenes ?? payload.scene;
    const scenes = Array.isArray(rawScenes) ? (rawScenes as Scene[]) : [];
    if (!scenes.length) {
        return <div className="py-8 text-center text-label text-[var(--s-faint)]">剧本还没有场景</div>;
    }
    return (
        <div>
            {scenes.map((scene, index) => (
                <SceneBlock key={index} scene={scene} onRewrite={onRewrite} />
            ))}
        </div>
    );
}
