"use client";

import { ArtifactContentView } from "@/features/canvas/components/artifact-content-view";
import { DocumentRenderer } from "./document-renderer";
import { OutlineRenderer } from "./outline-renderer";
import { ScriptRenderer } from "./script-renderer";
import { ShotPlanRenderer } from "./shot-plan-renderer";

/** 故事视图分体裁渲染（T4.F3）。 */
export function StoryRenderer({
    kind,
    payload,
    onRewrite,
}: {
    kind: string;
    payload: Record<string, unknown>;
    onRewrite: (text: string) => void;
}) {
    if (kind === "outline" || kind === "story_graph") return <OutlineRenderer payload={payload} onRewrite={onRewrite} />;
    if (kind === "script" || kind === "screenplay") return <ScriptRenderer payload={payload} onRewrite={onRewrite} />;
    if (kind === "shot_plan") return <ShotPlanRenderer payload={payload} onRewrite={onRewrite} />;
    if (kind === "analysis" || kind === "generated") return <DocumentRenderer payload={payload} onRewrite={onRewrite} />;
    return <ArtifactContentView payload={payload} />;
}
