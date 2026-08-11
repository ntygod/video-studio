"use client";

import { VolumeX, Volume2 } from "lucide-react";

import { ClipBlock } from "./clip-block";
import { TRACK_LABELS, type TimelineClip, type TimelineTrack } from "./types";
import { cn } from "@/shared/lib/utils";

export function TrackRow({
    track,
    duration,
    pxPerSec,
    selectedClipId,
    muted,
    solo,
    canSolo,
    onSelectClip,
    onChangeClip,
    onToggleMute,
    onToggleSolo,
}: {
    track: TimelineTrack;
    duration: number;
    pxPerSec: number;
    selectedClipId: string | null;
    muted: boolean;
    solo: boolean;
    canSolo: boolean;
    onSelectClip: (clipId: string) => void;
    onChangeClip: (clip: TimelineClip) => void;
    onToggleMute: () => void;
    onToggleSolo: () => void;
}) {
    const isAudio = ["voice", "music", "sfx"].includes(track.kind);
    const laneWidth = Math.max(200, duration * pxPerSec);
    return (
        <div className="flex w-max min-w-full items-stretch border-b border-[var(--hairline)] last:border-b-0">
            <div className="flex w-24 shrink-0 flex-col items-start justify-between gap-1 border-r border-[var(--hairline)] px-2 py-1.5">
                <span className="truncate text-caption font-medium text-[var(--s-ink)]">{TRACK_LABELS[track.kind] || track.kind}</span>
                {isAudio ? (
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            aria-label={muted ? "取消静音" : "静音轨道"}
                            onClick={onToggleMute}
                            className={cn("flex size-5 items-center justify-center rounded-[var(--r-xs)]", muted ? "bg-[var(--s-raised)] text-[var(--s-ink)]" : "text-[var(--s-faint)]")}
                        >
                            {muted ? <VolumeX className="size-3" /> : <Volume2 className="size-3" />}
                        </button>
                        <button
                            type="button"
                            aria-label={solo ? "取消独奏" : "独奏轨道"}
                            onClick={onToggleSolo}
                            disabled={!canSolo}
                            className={cn("rounded-[var(--r-xs)] px-1 text-caption", solo ? "bg-[var(--s-raised)] text-[var(--s-ink)]" : "text-[var(--s-faint)]")}
                        >
                            S
                        </button>
                    </div>
                ) : null}
            </div>
            <div
                className="relative min-h-[48px] shrink-0 overflow-hidden"
                style={{
                    width: laneWidth,
                    backgroundColor: "color-mix(in srgb, var(--s-canvas) 46%, transparent)",
                    backgroundImage: "linear-gradient(to right, var(--hairline) 1px, transparent 1px)",
                    backgroundSize: `${pxPerSec}px 100%`,
                }}
            >
                {track.clips.map((clip) => (
                    <ClipBlock key={clip.id} clip={clip} trackKind={track.kind} pxPerSec={pxPerSec} selected={selectedClipId === clip.id} onSelect={() => onSelectClip(clip.id)} onChange={onChangeClip} />
                ))}
            </div>
        </div>
    );
}
