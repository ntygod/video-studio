"use client";

import { BlockActions } from "./block-actions";

type Shot = {
    id?: string;
    title?: string;
    description?: string;
    shot_size?: string;
    camera_movement?: string;
    duration?: number;
    status?: string;
};

/** 分镜计划渲染器：镜头表格（与分镜墙共用语义）。 */
export function ShotPlanRenderer({ payload, onRewrite }: { payload: Record<string, unknown>; onRewrite: (text: string) => void }) {
    const rawShots = payload.shots;
    const shots = Array.isArray(rawShots) ? (rawShots as Shot[]) : [];
    if (!shots.length) {
        return <div className="py-8 text-center text-label text-[var(--s-faint)]">分镜计划还没有镜头</div>;
    }
    return (
        <div className="overflow-x-auto rounded-lg border border-[var(--hairline)]">
            <table className="w-full min-w-[640px] text-left text-label">
                <thead>
                    <tr className="border-b border-[var(--hairline)] text-caption text-[var(--s-faint)]">
                        <th className="px-3 py-2 font-medium">#</th>
                        <th className="px-3 py-2 font-medium">镜头</th>
                        <th className="px-3 py-2 font-medium">景别</th>
                        <th className="px-3 py-2 font-medium">运镜</th>
                        <th className="px-3 py-2 font-medium">时长</th>
                        <th className="px-3 py-2 font-medium">说明</th>
                        <th className="px-3 py-2 font-medium">状态</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-[var(--hairline)]">
                    {shots.map((shot, index) => (
                        <tr key={shot.id || index} className="align-top hover:bg-[var(--s-raised)]">
                            <td className="px-3 py-2 text-[var(--s-faint)]">{index + 1}</td>
                            <td className="px-3 py-2 font-medium text-[var(--s-ink)]">
                                <BlockActions text={shot.title || shot.description || ""} onRewrite={onRewrite} />
                                {shot.title || shot.id?.slice(0, 8) || "镜头"}
                            </td>
                            <td className="px-3 py-2 text-[var(--s-muted)]">{shot.shot_size || "—"}</td>
                            <td className="px-3 py-2 text-[var(--s-muted)]">{shot.camera_movement || "—"}</td>
                            <td className="px-3 py-2 text-[var(--s-muted)]">{shot.duration ? `${shot.duration}s` : "—"}</td>
                            <td className="max-w-[240px] px-3 py-2 text-[var(--s-text)]">{shot.description || ""}</td>
                            <td className="px-3 py-2 text-[var(--s-muted)]">{shot.status || "draft"}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
