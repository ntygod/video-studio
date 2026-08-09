"use client";

import { App, Button, Popconfirm, Spin, Upload } from "antd";
import { Paperclip, Trash2 } from "lucide-react";

import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { assetKindLabel } from "@/features/workspace/lib/labels";
import { mediaUrl, type Asset } from "@/services/api";
import { useDeleteAsset, useUploadAsset } from "@/services/queries";
import { relativeTime } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/empty-state";

/** 按 MIME 类型选择合适的预览方式。 */
function AssetPreview({ asset }: { asset: Asset }) {
    const url = mediaUrl(asset.uri);
    if (asset.mime_type.startsWith("image/")) {
        // eslint-disable-next-line @next/next/no-img-element -- 素材来自后端媒体目录，尺寸未知，不走 next/image 优化。
        return <img src={url} alt={asset.name} loading="lazy" className="mt-3 max-h-40 w-full rounded-md object-contain" />;
    }
    if (asset.mime_type.startsWith("video/")) {
        return <video src={url} controls preload="metadata" className="mt-3 max-h-40 w-full rounded-md" />;
    }
    if (asset.mime_type.startsWith("audio/")) {
        return <audio src={url} controls preload="metadata" className="mt-3 w-full" />;
    }
    return (
        <a href={url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-[11px] text-[var(--studio-action)] hover:underline">
            打开文件
        </a>
    );
}

/** 画布 · 素材：上传与管理当前作用域下的媒体。 */
export function MediaView() {
    const { message } = App.useApp();
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const { assets, assetsLoading, selectedUnit } = useWorkspaceData();

    const uploadAsset = useUploadAsset(projectId);
    const deleteAsset = useDeleteAsset(projectId, selectedUnitId);

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
        <div className="mx-auto w-full max-w-[900px] space-y-4 px-5 py-6 md:px-7">
            <div>
                <h1 className="text-[15px] font-semibold text-[var(--studio-ink)]">项目素材</h1>
                <p className="mt-1 text-[11px] leading-5 text-[var(--studio-muted)]">
                    上传图片、视频、音频或文档，供 AI 参考或用于最终成片。当前归属：
                    {selectedUnit ? selectedUnit.title : "整个项目"}。
                </p>
            </div>

            <Upload.Dragger
                accept="image/*,video/*,audio/*,.pdf,.txt,.md,.json,.srt"
                showUploadList={false}
                multiple
                beforeUpload={(file) => doUpload(file)}
                disabled={uploadAsset.isPending}
            >
                <div className="py-6">
                    <Paperclip className="mx-auto size-7 text-[var(--studio-action)]" />
                    <div className="mt-2 text-[13px] font-medium text-[var(--studio-ink)]">
                        {uploadAsset.isPending ? "正在上传…" : "点击或拖拽上传素材"}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--studio-faint)]">图片、视频、音频、文档均可作为 AI 参考</div>
                </div>
            </Upload.Dragger>

            {assetsLoading && !assets.length ? (
                <div className="flex justify-center py-16">
                    <Spin />
                </div>
            ) : assets.length === 0 ? (
                <EmptyState
                    title="这里还没有素材"
                    description="上传一些参考图或视频，AI 在生成分镜和剪辑方案时会用到它们。"
                />
            ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                    {assets.map((asset) => (
                        <article key={asset.id} className="rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] p-3">
                            <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                    <div className="truncate text-[13px] font-medium text-[var(--studio-ink)]">
                                        {asset.name || asset.kind}
                                    </div>
                                    <div className="mt-0.5 truncate text-[10px] text-[var(--studio-faint)]">
                                        {assetKindLabel(asset.kind)} · {relativeTime(asset.created_at)}
                                    </div>
                                </div>
                                <Popconfirm title="删除此素材？" okText="删除" cancelText="取消" onConfirm={() => void remove(asset)}>
                                    <Button type="text" size="small" danger aria-label="删除素材" icon={<Trash2 className="size-3.5" />} />
                                </Popconfirm>
                            </div>
                            <AssetPreview asset={asset} />
                        </article>
                    ))}
                </div>
            )}
        </div>
    );
}
