"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Save, Zap } from "lucide-react";
import { useRouter } from "next/navigation";

import { Player } from "./player";
import { Ruler } from "./ruler";
import { TrackRow } from "./track-row";
import { Timeline, TimelineClip, TimelineTrack } from "./types";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useAddArtifactVersion, useCompileTimeline } from "@/services/queries";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { Button, Segmented, Surface, Text, useApp } from "@/shared/ui";

const PX_PER_SEC_OPTIONS = [
    { value: 40, label: "40" },
    { value: 80, label: "80" },
    { value: 160, label: "160" },
];

/**
 * 时间线视图（T4.F1）。
 * <p>
 * 播放器 + 轨道容器，自绘（div + transform）。v1 范围：拖动改时长与重排、
 * 静音/独奏、音量、点击 clip 跳到对应镜头卡。
 */
export function TimelineView() {
    const { message } = useApp();
    const router = useRouter();
    const { projectId, selectedUnitId, hrefFor } = useWorkspaceRoute();
    const { assets, artifacts } = useWorkspaceData();

    const compileTimeline = useCompileTimeline(projectId);
    const saveVersion = useAddArtifactVersion(projectId);

    const [timeline, setTimeline] = useState<Timeline | null>(null);
    const [artifactId, setArtifactId] = useState<string | null>(null);
    const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
    const [pxPerSec, setPxPerSec] = useState(80);
    const [mutedTracks, setMutedTracks] = useState<Set<string>>(new Set());
    const [soloTrack, setSoloTrack] = useState<string | null>(null);

    const timelineArtifact = useMemo(() => artifacts.find((artifact) => artifact.kind === "timeline" && artifact.unit_id === selectedUnitId) || null, [artifacts, selectedUnitId]);

    useEffect(() => {
        const payload = timelineArtifact?.current_version?.payload;
        const persisted = payload && Array.isArray(payload.tracks) ? (payload as unknown as Timeline) : null;
        setTimeline(persisted);
        setArtifactId(timelineArtifact?.id || null);
        setSelectedClipId(null);
    }, [projectId, selectedUnitId, timelineArtifact?.id, timelineArtifact?.current_version_id]);

    const assetById = useMemo(() => {
        const map = new Map<string, (typeof assets)[number]>();
        assets.forEach((asset) => map.set(asset.id, asset));
        return map;
    }, [assets]);

    const selectedClip = useMemo(() => {
        if (!timeline || !selectedClipId) return null;
        for (const track of timeline.tracks) {
            const clip = track.clips.find((item) => item.id === selectedClipId);
            if (clip) return { clip, trackKind: track.kind };
        }
        return null;
    }, [timeline, selectedClipId]);

    const selectedAsset = selectedClip?.clip.asset_id ? assetById.get(selectedClip.clip.asset_id) : undefined;
    const visibleTracks = useMemo(() => timeline?.tracks || [], [timeline]);

    const updateClip = (trackId: string, next: TimelineClip) => {
        setTimeline((current) => {
            if (!current) return current;
            return {
                ...current,
                tracks: current.tracks.map((track) => (track.id === trackId ? { ...track, clips: track.clips.map((clip) => (clip.id === next.id ? next : clip)) } : track)),
            };
        });
    };

    const setVolume = (clipId: string, volumeDb: number) => {
        visibleTracks.forEach((track) => {
            if (track.clips.some((clip) => clip.id === clipId)) {
                const clip = track.clips.find((item) => item.id === clipId);
                if (clip) updateClip(track.id, { ...clip, volume_db: volumeDb });
            }
        });
    };

    const compile = async () => {
        try {
            const result = await compileTimeline.mutateAsync({ unit_id: selectedUnitId });
            setTimeline(result.timeline as Timeline);
            setArtifactId(result.artifact.id);
            setSelectedClipId(null);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "时间线编译失败");
        }
    };

    const save = async () => {
        if (!timeline || !artifactId) return;
        try {
            await saveVersion.mutateAsync({ artifactId, payload: timeline as unknown as Record<string, unknown>, note: "时间线微调" });
            message.success("时间线已保存为新版本");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "保存失败");
        }
    };

    const jumpToShot = () => {
        const unitId = (selectedClip?.clip.metadata?.unit_id as string | undefined) || selectedUnitId;
        if (!unitId) return;
        router.push(hrefFor("board", unitId));
    };

    return (
        <div className="mx-auto w-full max-w-[1280px] space-y-4 px-5 py-6 md:px-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <Text as="h1" variant="heading" tone="ink">
                        时间线
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-0.5">
                        拖动片段改位置、拖右缘改时长，保存后生成新版本。
                    </Text>
                </div>
                <div className="flex items-center gap-2">
                    <Segmented size="small" value={pxPerSec} onChange={(value) => setPxPerSec(value as number)} options={PX_PER_SEC_OPTIONS} aria-label="时间轴缩放" />
                    <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={compileTimeline.isPending} onClick={() => void compile()}>
                        {timeline ? "重新编译" : "编译时间线"}
                    </Button>
                    <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} disabled={!timeline || !artifactId} loading={saveVersion.isPending} onClick={() => void save()}>
                        保存时间线
                    </Button>
                </div>
            </div>

            {compileTimeline.isError ? (
                <ErrorPanel title="时间线编译失败" message={compileTimeline.error.message} onRetry={() => void compile()} />
            ) : compileTimeline.isPending && !timeline ? (
                <div className="py-20 text-center text-label text-[var(--s-faint)]">正在编译时间线…</div>
            ) : !timeline ? (
                <EmptyState
                    title="还没有时间线"
                    description="准备好素材或剪辑方案后，再明确编译第一版时间线。"
                    action={
                        <Button variant="primary" icon={<RefreshCw className="size-3.5" />} loading={compileTimeline.isPending} onClick={() => void compile()}>
                            编译第一版
                        </Button>
                    }
                />
            ) : (
                <>
                    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
                        <Player src={selectedAsset?.uri || ""} mimeType={selectedAsset?.mime_type} label={selectedClip ? `片段 · ${selectedClip.trackKind}` : "点击片段预览"} width={timeline.width} height={timeline.height} />
                        <Surface level="panel" radius="md" hairline lift inset="3" className="min-w-0">
                            <div className="mb-2 flex flex-wrap items-center gap-3 text-caption text-[var(--s-muted)]">
                                <span>
                                    {timeline.width}×{timeline.height} · {timeline.fps}fps
                                </span>
                                <span>总时长 {timeline.duration.toFixed(1)}s</span>
                                {selectedClip ? (
                                    <>
                                        <button type="button" onClick={jumpToShot} className="flex items-center gap-1 text-[var(--s-muted)] hover:text-[var(--s-ink)] hover:underline">
                                            <Zap className="size-3" />
                                            跳到镜头卡
                                        </button>
                                        <label className="flex items-center gap-1">
                                            音量
                                            <input type="range" min={-20} max={6} step={1} value={selectedClip.clip.volume_db} onChange={(event) => setVolume(selectedClip.clip.id, Number(event.target.value))} aria-label="片段音量" className="w-24" />
                                            <span>{selectedClip.clip.volume_db}dB</span>
                                        </label>
                                    </>
                                ) : null}
                            </div>
                            <div className="hide-scrollbar overflow-x-auto">
                                <Ruler duration={timeline.duration} pxPerSec={pxPerSec} />
                                <div className="space-y-1 pt-1">
                                    {visibleTracks.map((track) => (
                                        <TrackRow
                                            key={track.id}
                                            track={track}
                                            duration={timeline.duration}
                                            pxPerSec={pxPerSec}
                                            selectedClipId={selectedClipId}
                                            muted={mutedTracks.has(track.id)}
                                            solo={soloTrack === track.id}
                                            canSolo={soloTrack === null || soloTrack === track.id}
                                            onSelectClip={setSelectedClipId}
                                            onChangeClip={(clip) => updateClip(track.id, clip)}
                                            onToggleMute={() =>
                                                setMutedTracks((current) => {
                                                    const next = new Set(current);
                                                    if (next.has(track.id)) next.delete(track.id);
                                                    else next.add(track.id);
                                                    return next;
                                                })
                                            }
                                            onToggleSolo={() => setSoloTrack((current) => (current === track.id ? null : track.id))}
                                        />
                                    ))}
                                </div>
                            </div>
                        </Surface>
                    </div>
                </>
            )}
        </div>
    );
}
