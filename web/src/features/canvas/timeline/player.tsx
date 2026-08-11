"use client";

import { mediaUrl } from "@/services/api/http";

/** 16:9 / 9:16 预览（T4.F1）：选中 clip 的素材或占位黑场。 */
export function Player({
    src,
    mimeType,
    label,
    width,
    height,
}: {
    src: string;
    mimeType?: string;
    label: string;
    width: number;
    height: number;
}) {
    const isVideo = mimeType ? mimeType.startsWith("video/") : false;
    return (
        <div
            className="flex w-full items-center justify-center overflow-hidden rounded-[var(--r-md)] border border-[var(--hairline)] bg-[var(--s-canvas)]"
            style={{ aspectRatio: `${width} / ${height}` }}
        >
            {src ? (
                isVideo ? (
                    <video src={mediaUrl(src)} controls className="h-full w-full object-contain" />
                ) : (
                    <img src={mediaUrl(src)} alt={label} className="h-full w-full object-contain" />
                )
            ) : (
                <div className="px-4 text-center text-caption text-white/50">{label}</div>
            )}
        </div>
    );
}
