"use client";

import { useEffect, useMemo, useState } from "react";
import { Paperclip, Trash2 } from "lucide-react";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { assetKindLabel } from "@/features/workspace/lib/labels";
import { mediaUrl, type Asset } from "@/services/api";
import { useDeleteAsset, useUploadAsset } from "@/services/queries";
import { relativeTime } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/empty-state";
import { cn } from "@/shared/lib/utils";
import { Button, MediaFrame, Popconfirm, Select, Spin, Text, Upload, useApp } from "@/shared/ui";

/** 音频波形：从 .wave.json 拉 200 个峰值画成条形。 */
function Waveform({ url }: { url: string }) {
    const [peaks, setPeaks] = useState<number[]>([]);
    useEffect(() => {
        let alive = true;
        fetch(url)
            .then((response) => (response.ok ? response.json() : []))
            .then((data) => {
                if (alive && Array.isArray(data)) setPeaks(data.slice(0, 200));
            })
            .catch(() => {});
        return () => {
            alive = false;
        };
    }, [url]);
    if (!peaks.length) return null;
    return (
        <div className="flex h-8 items-center gap-px">
            {peaks.map((peak, index) => (
                <span
                    key={index}
                    className="w-px flex-1 rounded-full bg-[var(--s-ink)]"
                    style={{ height: `${Math.max(8, peak * 100)}%` }}
                />
            ))}
        </div>
    );
}

/** 素材卡：缩略图/视频悬停预览/波形 + 血缘链。 */
function AssetCard({
    asset,
    unitName,
    selected,
    onSelect,
    onDelete,
}: {
    asset: Asset;
    unitName: string;
    selected: boolean;
    onSelect: () => void;
    onDelete: () => void;
}) {
    const previewUrl = mediaUrl(asset.thumb_uri || asset.uri);
    const generation = asset.generation || {};
    const prompt = typeof generation.prompt === "string" ? generation.prompt : "";
    const provider = typeof generation.provider === "string" ? generation.provider : "";
    const waveUrl = asset.thumb_uri?.endsWith(".wave.json") ? mediaUrl(asset.thumb_uri) : "";

    return (
        <article
            draggable
            onClick={onSelect}
            onDragStart={(event) => event.dataTransfer.setData("text/asset-id", asset.id)}
            className={cn(
                "group cursor-grab rounded-[var(--r-md)] border bg-[var(--s-panel)] p-2.5 shadow-[var(--lift)] transition-[border-color,box-shadow] duration-[var(--dur-base)] ease-[var(--ease-out)] hover:shadow-[var(--s-shadow-md)] active:cursor-grabbing",
                selected ? "border-[var(--s-action)]" : "border-[var(--hairline)] hover:border-[var(--hairline-strong)]",
            )}
        >
            <MediaFrame ratio="16 / 9">
                {asset.mime_type.startsWith("image/") ? (
                    <img src={previewUrl} alt={asset.name} loading="lazy" className="h-full w-full object-cover" />
                ) : asset.mime_type.startsWith("video/") ? (
                    <video src={mediaUrl(asset.uri)} muted preload="metadata" className="h-full w-full object-cover" />
                ) : (
                    <div className="flex h-full items-center justify-center text-[var(--s-faint)]">
                        {assetKindLabel(asset.kind)}
                    </div>
                )}
                <span className="absolute bottom-1 left-1 rounded bg-black/55 px-1 py-0.5 text-caption text-white">
                    {assetKindLabel(asset.kind)}
                </span>
            </MediaFrame>
            {waveUrl ? <Waveform url={waveUrl} /> : null}
            <div className="mt-2 flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <Text as="div" variant="label" tone="ink" weight={500} truncate>
                        {asset.name || asset.kind}
                    </Text>
                    <Text variant="caption" tone="faint" className="mt-0.5 block">
                        {relativeTime(asset.created_at)} · 归属：{unitName || "未使用"}
                    </Text>
                    {prompt ? (
                        <p className="mt-1 line-clamp-2 text-caption leading-4 text-[var(--s-muted)]">
                            {provider ? `${provider}：` : ""}
                            {prompt}
                        </p>
                    ) : null}
                </div>
                <Popconfirm title="删除此素材？" okText="删除" cancelText="取消" onConfirm={onDelete}>
                    <Button variant="ghost" size="sm" danger aria-label="删除素材" icon={<Trash2 className="size-3.5" />} />
                </Popconfirm>
            </div>
        </article>
    );
}

/** 画布 · 素材：缩略图网格、筛选、视频悬停预览、音频波形、血缘链，可拖到分镜卡。 */
export function MediaView() {
    const { message } = useApp();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { assets, assetsLoading, selectedUnit, unitTree } = useWorkspaceData();
    const [kind, setKind] = useState<string>("all");
    const [source, setSource] = useState<string>("all");
    const [used, setUsed] = useState<string>("all");
    const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);

    const uploadAsset = useUploadAsset(projectId);
    const deleteAsset = useDeleteAsset(projectId, selectedUnitId);

    const unitNameById = useMemo(() => {
        const map = new Map<string, string>();
        const walk = (nodes: typeof unitTree) => {
            nodes.forEach((node) => {
                map.set(node.id, node.title);
                walk(node.children);
            });
        };
        walk(unitTree);
        return map;
    }, [unitTree]);

    const filtered = useMemo(() => {
        return assets.filter((asset) => {
            if (kind !== "all" && asset.kind !== kind) return false;
            const provider = String((asset.generation || {}).provider || "upload");
            if (source === "upload" && provider !== "upload") return false;
            if (source === "ai" && provider === "upload") return false;
            const attached = Boolean(asset.unit_id);
            if (used === "used" && !attached) return false;
            if (used === "unused" && attached) return false;
            return true;
        });
    }, [assets, kind, source, used]);

    useEffect(() => {
        if (selectedAssetId && filtered.some((asset) => asset.id === selectedAssetId)) return;
        setSelectedAssetId(filtered[0]?.id || null);
    }, [filtered, selectedAssetId]);

    const selectedAsset = filtered.find((asset) => asset.id === selectedAssetId) || null;

    const doUpload = async (file: File) => {
        try {
            await uploadAsset.mutateAsync({ file, kind: "reference", name: file.name, unitId: selectedUnitId });
            message.success("素材已上传");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "上传失败");
        }
        return false;
    };

    const remove = async (asset: Asset) => {
        try {
            await deleteAsset.mutateAsync(asset.id);
            message.success("素材已删除");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1200px] space-y-4 px-5 py-6 md:px-7">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                <Text as="h1" variant="heading" tone="ink">
                    项目素材
                </Text>
                <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                    当前归属：{selectedUnit ? selectedUnit.title : "整个项目"}。拖拽素材卡到分镜墙即可挂到镜头。
                </Text>
                </div>
                <span className="rounded-full bg-[var(--s-raised)] px-3 py-1 text-caption text-[var(--s-muted)]">
                    {filtered.length} 个素材
                </span>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--hairline)] pb-3">
                <Select
                    size="small"
                    value={kind}
                    onChange={setKind}
                    style={{ width: 120 }}
                    options={[
                        { value: "all", label: "全部类型" },
                        { value: "image", label: "图片" },
                        { value: "video", label: "视频" },
                        { value: "voice", label: "配音" },
                        { value: "audio", label: "音频" },
                        { value: "reference", label: "参考" },
                        { value: "render", label: "成片" },
                    ]}
                />
                <Select
                    size="small"
                    value={source}
                    onChange={setSource}
                    style={{ width: 120 }}
                    options={[
                        { value: "all", label: "全部来源" },
                        { value: "ai", label: "AI 生成" },
                        { value: "upload", label: "用户上传" },
                    ]}
                />
                <Select
                    size="small"
                    value={used}
                    onChange={setUsed}
                    style={{ width: 120 }}
                    options={[
                        { value: "all", label: "全部使用状态" },
                        { value: "used", label: "已使用" },
                        { value: "unused", label: "未使用" },
                    ]}
                />
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
                <section className="min-w-0 space-y-4">
                    <Upload.Dragger
                        accept="image/*,video/*,audio/*,.pdf,.txt,.md,.json,.srt"
                        showUploadList={false}
                        multiple
                        beforeUpload={(file) => doUpload(file)}
                        disabled={uploadAsset.isPending}
                    >
                        <div className="flex items-center justify-center gap-3 py-3">
                            <Paperclip className="size-5 text-[var(--s-faint)]" />
                            <Text as="div" variant="label" tone="ink" weight={500}>
                                {uploadAsset.isPending ? "正在上传…" : "拖入图片、视频、音频、字幕或参考文档"}
                            </Text>
                        </div>
                    </Upload.Dragger>

                    {assetsLoading && !assets.length ? (
                        <div className="flex justify-center py-16">
                            <Spin />
                        </div>
                    ) : filtered.length === 0 ? (
                        <EmptyState
                            title={assets.length ? "没有符合条件的素材" : "这里还没有素材"}
                            description={assets.length ? "换个筛选条件试试。" : "上传一些参考图或视频，AI 生成时会用到它们。"}
                        />
                    ) : (
                        <div className={cn("grid gap-3", assets.length > 50 ? "sm:grid-cols-3 2xl:grid-cols-4" : "sm:grid-cols-2 lg:grid-cols-3")}>
                            {filtered.map((asset) => (
                                <AssetCard
                                    key={asset.id}
                                    asset={asset}
                                    unitName={asset.unit_id ? unitNameById.get(asset.unit_id) || "已使用" : ""}
                                    selected={asset.id === selectedAssetId}
                                    onSelect={() => setSelectedAssetId(asset.id)}
                                    onDelete={() => void remove(asset)}
                                />
                            ))}
                        </div>
                    )}
                </section>

                {selectedAsset ? (
                    <aside className="hidden xl:block">
                        <div className="sticky top-0 rounded-[var(--r-md)] border border-[var(--hairline)] bg-[var(--s-panel)] p-3 shadow-[var(--lift)]">
                            <MediaFrame ratio="16 / 10">
                                {selectedAsset.mime_type.startsWith("image/") ? (
                                    <img
                                        src={mediaUrl(selectedAsset.thumb_uri || selectedAsset.uri)}
                                        alt={selectedAsset.name}
                                        className="h-full w-full object-cover"
                                    />
                                ) : selectedAsset.mime_type.startsWith("video/") ? (
                                    <video src={mediaUrl(selectedAsset.uri)} muted controls className="h-full w-full object-cover" />
                                ) : (
                                    <div className="flex h-full items-center justify-center text-label text-[var(--s-muted)]">
                                        {assetKindLabel(selectedAsset.kind)}
                                    </div>
                                )}
                            </MediaFrame>
                            <div className="mt-3 flex items-start gap-2">
                                <div className="min-w-0 flex-1">
                                    <Text as="h2" variant="body" tone="ink" weight={600} truncate>
                                        {selectedAsset.name || selectedAsset.kind}
                                    </Text>
                                    <Text variant="caption" tone="faint" className="mt-0.5 block">
                                        {assetKindLabel(selectedAsset.kind)} · {selectedAsset.mime_type}
                                    </Text>
                                </div>
                                <Popconfirm title="删除此素材？" okText="删除" cancelText="取消" onConfirm={() => void remove(selectedAsset)}>
                                    <Button variant="ghost" size="sm" danger aria-label="删除素材" icon={<Trash2 className="size-3.5" />} />
                                </Popconfirm>
                            </div>
                            <dl className="mt-3 divide-y divide-[var(--hairline)] text-caption">
                                <div className="grid grid-cols-[64px_1fr] gap-2 py-2">
                                    <dt className="text-[var(--s-faint)]">归属</dt>
                                    <dd className="m-0 text-[var(--s-text)]">
                                        {selectedAsset.unit_id ? unitNameById.get(selectedAsset.unit_id) || "已使用" : "未使用"}
                                    </dd>
                                </div>
                                <div className="grid grid-cols-[64px_1fr] gap-2 py-2">
                                    <dt className="text-[var(--s-faint)]">来源</dt>
                                    <dd className="m-0 text-[var(--s-text)]">
                                        {String((selectedAsset.generation || {}).provider || "用户上传")}
                                    </dd>
                                </div>
                                <div className="grid grid-cols-[64px_1fr] gap-2 py-2">
                                    <dt className="text-[var(--s-faint)]">创建时间</dt>
                                    <dd className="m-0 text-[var(--s-text)]">{relativeTime(selectedAsset.created_at)}</dd>
                                </div>
                            </dl>
                            {String((selectedAsset.generation || {}).prompt || "") ? (
                                <div className="mt-3 rounded-[var(--r-sm)] bg-[var(--s-raised)] p-3">
                                    <Text variant="caption" tone="faint">生成提示词</Text>
                                    <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                                        {String((selectedAsset.generation || {}).prompt)}
                                    </Text>
                                </div>
                            ) : null}
                        </div>
                    </aside>
                ) : null}
            </div>
        </div>
    );
}
