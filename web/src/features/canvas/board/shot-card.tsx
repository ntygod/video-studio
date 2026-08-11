"use client";

import { useState } from "react";
import { Check, Clapperboard, ImagePlus, RefreshCw, Upload } from "lucide-react";

import { ShotCandidates } from "@/features/canvas/board/shot-candidates";
import type { Asset, CreativeUnit } from "@/services/api";
import { mediaUrl } from "@/services/api";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { ProgressRing, StatusDot } from "@/shared/ui/indicators";
import { MediaFrame } from "@/shared/ui/media-frame";
import { Stack } from "@/shared/ui/stack";
import { Text } from "@/shared/ui/text";

/**
 * 分镜卡（docs/ui-craft.md §4.1）。
 * 媒体出血到卡片边缘、无边框；整卡点击选中；生成中 = shimmer + 进度环，不盖灰蒙层。
 */
export function ShotCard({
    unit,
    candidates,
    index,
    selected,
    onSelect,
    onGenerate,
    onUpload,
    onDropCard,
    onAttachAsset,
    onReorder,
    busy,
    progress,
}: {
    unit: CreativeUnit;
    candidates: Asset[];
    index: number;
    selected: boolean;
    onSelect: (selected: boolean) => void;
    onGenerate: (capability: "image" | "video") => void;
    onUpload: (file: File) => void;
    onDropCard: (targetId: string) => void;
    onAttachAsset: (assetId: string) => void;
    onReorder: (unitId: string, orderIndex: number) => void;
    busy: boolean;
    /** 当前生成任务的进度 0~1；未知时不显示百分比。 */
    progress?: number;
}) {
    const [candidateIndex, setCandidateIndex] = useState(0);
    const active = candidates[candidateIndex];
    const image = active?.mime_type.startsWith("image/") ? active : candidates.find((item) => item.mime_type.startsWith("image/"));
    const duration = (active?.metadata as { duration?: number } | undefined)?.duration;
    const hasMedia = candidates.length > 0;

    const toggleSelect = () => onSelect(!selected);

    return (
        <Card
            media
            selected={selected}
            interactive
            draggable
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            aria-label={`分镜 ${index + 1}：${unit.title}`}
            onClick={toggleSelect}
            onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                if ((event.target as HTMLElement).closest("button,label,a,input")) return;
                event.preventDefault();
                toggleSelect();
            }}
            onDragStart={(event) => event.dataTransfer.setData("text/unit-id", unit.id)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
                event.preventDefault();
                const dragged = event.dataTransfer.getData("text/unit-id");
                if (dragged && dragged !== unit.id) {
                    onDropCard(unit.id);
                    return;
                }
                const assetId = event.dataTransfer.getData("text/asset-id");
                if (assetId) onAttachAsset(assetId);
            }}
            className={cn(busy && "opacity-95")}
        >
            <MediaFrame ratio="16 / 9">
                {image ? (
                    <img
                        src={mediaUrl(image.thumb_uri || image.uri)}
                        alt={unit.title}
                        loading="lazy"
                        className="h-full w-full object-cover"
                    />
                ) : (
                    <div className="flex h-full items-center justify-center text-caption text-[var(--s-faint)]">
                        {unit.unit_type === "shot" ? "还没有画面" : unit.unit_type}
                    </div>
                )}

                {/* 左上角：编号 + 自绘勾选圈（hover 才升起） */}
                <span className="absolute left-2 top-2 font-mono text-caption font-[450] text-[var(--s-ink)] drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]">
                    {String(index + 1).padStart(2, "0")}
                </span>
                <span
                    aria-hidden
                    className={cn(
                        "absolute left-2 top-8 flex size-5 items-center justify-center rounded-full border transition-all duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                        selected
                            ? "border-[var(--s-ink)] bg-[var(--s-ink)] text-[var(--s-base)] opacity-100"
                            : "border-[var(--hairline-strong)] bg-black/30 opacity-0 group-hover:opacity-100",
                    )}
                >
                    {selected ? <Check className="size-3" strokeWidth={3} /> : null}
                </span>

                {/* 生成中：shimmer + 环形进度，不盖灰蒙层 */}
                {busy ? (
                    <div className="absolute inset-0 z-10 flex items-center justify-center">
                        <div className="s-shimmer absolute inset-0" />
                        <ProgressRing
                            value={progress}
                            indeterminate={!progress}
                            size={44}
                            className="relative"
                        />
                    </div>
                ) : null}

                {/* hover：底部操作条从下缘滑入。蒙层恒为黑，图标固定白色——
                    用 --s-ink 在浅色主题下会变成近黑，压在黑色渐变上等于看不见。 */}
                <div
                    className="absolute inset-x-0 bottom-0 z-10 flex translate-y-full items-center justify-end gap-1 bg-gradient-to-t from-black/70 to-transparent px-2 pb-2 pt-6 transition-transform duration-[var(--dur-base)] ease-[var(--ease-out)] group-hover:translate-y-0"
                    onClick={(event) => event.stopPropagation()}
                >
                    <IconButton
                        label="生成图片"
                        icon={<ImagePlus className="size-4" />}
                        onClick={() => onGenerate("image")}
                        className="!text-white hover:!bg-white/15"
                    />
                    <IconButton
                        label="生成视频"
                        icon={<Clapperboard className="size-4" />}
                        onClick={() => onGenerate("video")}
                        className="!text-white hover:!bg-white/15"
                    />
                    <IconButton
                        label="重新生成"
                        icon={<RefreshCw className="size-4" />}
                        onClick={() => onGenerate("image")}
                        className="!text-white hover:!bg-white/15"
                    />
                    <label className="flex cursor-pointer items-center rounded-[var(--r-sm)] px-1 py-1 text-white transition-colors hover:bg-white/15">
                        <Upload className="size-4" />
                        <span className="sr-only">上传替换</span>
                        <input
                            type="file"
                            accept="image/*,video/*"
                            className="hidden"
                            onChange={(event) => {
                                const file = event.target.files?.[0];
                                if (file) onUpload(file);
                                event.target.value = "";
                            }}
                        />
                    </label>
                </div>
            </MediaFrame>

            <Stack gap="1" className="p-2.5">
                <div className="flex items-start justify-between gap-2">
                    <Text as="h3" variant="body" tone="ink" weight={600} truncate>
                        {unit.title}
                    </Text>
                    {/* 没有任何素材时是"未开始"，不该显示绿色的完成点 */}
                    <StatusDot tone={busy ? "active" : hasMedia ? "success" : "idle"} pulse={busy} />
                </div>
                {unit.summary ? (
                    <Text as="p" variant="caption" tone="muted" className="line-clamp-2">
                        {unit.summary}
                    </Text>
                ) : null}
                <div className="flex items-center justify-between gap-2">
                    <Text variant="mono" tone="faint">
                        {candidates.length} 候选{duration ? ` · ${duration.toFixed(1)}s` : ""}
                    </Text>
                    <ShotCandidates count={candidates.length} active={candidateIndex} onChange={setCandidateIndex} />
                </div>
            </Stack>
        </Card>
    );
}
