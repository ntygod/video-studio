/** 时间线前端模型（与后端 TimelineIR 对应）。 */
export type TimelineClip = {
    id: string;
    asset_id: string | null;
    range: { start: number; duration: number };
    source_in: number;
    speed: number;
    volume_db: number;
    metadata: Record<string, unknown>;
};

export type TimelineTrack = {
    id: string;
    kind: string;
    name: string;
    clips: TimelineClip[];
};

export type Timeline = {
    width: number;
    height: number;
    fps: number;
    tracks: TimelineTrack[];
    duration: number;
};

export const TRACK_LABELS: Record<string, string> = {
    video: "视频",
    image: "图片",
    voice: "配音",
    music: "音乐",
    sfx: "音效",
    subtitle: "字幕",
};
