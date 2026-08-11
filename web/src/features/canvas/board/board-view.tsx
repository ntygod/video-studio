"use client";

import { useMemo, useRef, useState } from "react";
import { LayoutGrid, List, Plus, Sparkles } from "lucide-react";

import { BatchGenerateModal } from "@/features/canvas/board/batch-generate";
import { ShotCard } from "@/features/canvas/board/shot-card";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { useWorkspaceStore } from "@/features/workspace/stores/use-workspace-store";
import type { Asset, CreativeUnit } from "@/services/api";
import { isJobActive } from "@/services/api";
import { useJobs, useStartGeneration, useUpdateAsset, useUpdateUnit, useUploadAsset } from "@/services/queries";
import { Button, Segmented, Text, Tooltip, useApp } from "@/shared/ui";
import { EmptyState } from "@/shared/ui/empty-state";

/** 分镜墙：网格/列表切换、批量工具条、生成中覆盖层。 */
export function BoardView() {
    const { message } = useApp();
    const { projectId } = useWorkspaceRoute();
    const { unitTree, assets } = useWorkspaceData();
    const [mode, setMode] = useState<"grid" | "list">("grid");
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [batchOpen, setBatchOpen] = useState(false);
    const [shots, setShots] = useState<CreativeUnit[]>([]);
    // FLIP 重排：记录旧位置，paint 后反向位移再过渡回原位。
    const cardRefs = useRef(new Map<string, HTMLDivElement | null>());
    const prevOffsets = useRef(new Map<string, number>());

    const startGeneration = useStartGeneration(projectId);
    const uploadAsset = useUploadAsset(projectId);
    const updateUnit = useUpdateUnit(projectId);
    const updateAsset = useUpdateAsset(projectId);
    const jobsQuery = useJobs(projectId);
    const requestUnitCreate = useWorkspaceStore((state) => state.requestUnitCreate);
    const setStructureDrawer = useWorkspaceStore((state) => state.setStructureDrawer);

    const flatShots = useMemo(() => {
        const result: CreativeUnit[] = [];
        const walk = (nodes: typeof unitTree) => {
            nodes.forEach((node) => {
                if (node.unit_type === "shot") result.push(node);
                walk(node.children);
            });
        };
        walk(unitTree);
        return result;
    }, [unitTree]);

    const orderedShots = shots.length === flatShots.length ? shots : flatShots;
    const jobs = jobsQuery.data || [];
    const assetsByUnit = useMemo(() => {
        const map = new Map<string, Asset[]>();
        assets.forEach((asset) => {
            if (!asset.unit_id) return;
            const list = map.get(asset.unit_id) || [];
            list.push(asset);
            map.set(asset.unit_id, list);
        });
        return map;
    }, [assets]);

    const toggleSelect = (unitId: string, checked: boolean) => {
        setSelected((current) => {
            const next = new Set(current);
            if (checked) next.add(unitId);
            else next.delete(unitId);
            return next;
        });
    };

    const generate = async (unit: CreativeUnit, capability: "image" | "video") => {
        try {
            await startGeneration.mutateAsync({
                unit_id: unit.id,
                capability,
                prompt: `根据单元「${unit.title}」${unit.summary ? `（${unit.summary}）` : ""}生成${capability === "image" ? "分镜图" : "镜头视频"}`,
            });
            message.success("已派发生成任务");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "派发失败");
        }
    };

    const attachAsset = async (unitId: string, assetId: string) => {
        try {
            await updateAsset.mutateAsync({ assetId, unitId });
            message.success("素材已挂到镜头");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "挂载失败");
        }
    };

    const upload = async (unit: CreativeUnit, file: File) => {
        try {
            await uploadAsset.mutateAsync({ file, kind: "image", name: file.name, unitId: unit.id });
            message.success("已上传替换素材");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "上传失败");
        }
    };

    const reorder = async (targetId: string) => {
        const draggedId = [...selected][0];
        if (!draggedId || draggedId === targetId) return;
        const fromIndex = orderedShots.findIndex((item) => item.id === draggedId);
        const toIndex = orderedShots.findIndex((item) => item.id === targetId);
        if (fromIndex < 0 || toIndex < 0) return;
        const next = [...orderedShots];
        const [moved] = next.splice(fromIndex, 1);
        next.splice(toIndex, 0, moved);

        const oldOffsets = new Map<string, number>();
        cardRefs.current.forEach((element, id) => {
            if (element) oldOffsets.set(id, element.offsetTop);
        });
        prevOffsets.current = oldOffsets;
        setShots(next);
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                next.forEach((item) => {
                    const element = cardRefs.current.get(item.id);
                    const prev = prevOffsets.current.get(item.id);
                    if (!element || prev === undefined) return;
                    const delta = prev - element.offsetTop;
                    if (delta === 0) return;
                    element.style.transition = "none";
                    element.style.transform = `translateY(${delta}px)`;
                    requestAnimationFrame(() => {
                        element.style.transition = "transform 200ms cubic-bezier(0.65,0,0.35,1)";
                        element.style.transform = "";
                    });
                });
            });
        });

        try {
            for (let index = 0; index < next.length; index += 1) {
                if (next[index].order_index !== index) {
                    await updateUnit.mutateAsync({ unitId: next[index].id, patch: { order_index: index } });
                }
            }
        } catch (error) {
            message.error(error instanceof Error ? error.message : "排序保存失败");
        }
    };

    return (
        <div className="mx-auto w-full max-w-[1200px] space-y-4 px-5 py-6 md:px-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <Text as="h1" variant="heading" tone="ink">
                        分镜墙
                    </Text>
                    <Text as="p" variant="caption" tone="muted" className="mt-0.5">
                        {flatShots.length ? `${flatShots.length} 个镜头 · 拖拽卡片可重排，悬停卡片可生成或上传素材` : "把场景拆成可生产的镜头，再为每个镜头选择画面候选。"}
                    </Text>
                </div>
                <div className="flex items-center gap-2">
                    {selected.size ? (
                        <Tooltip title={`已选 ${selected.size} 个镜头`}>
                            <Button icon={<Sparkles className="size-3.5" />} onClick={() => setBatchOpen(true)}>
                                批量生成（{selected.size}）
                            </Button>
                        </Tooltip>
                    ) : null}
                    {flatShots.length ? (
                        <Segmented
                            size="small"
                            value={mode}
                            onChange={(value) => setMode(value as "grid" | "list")}
                            options={[
                                { value: "grid", icon: <LayoutGrid className="size-3.5" /> },
                                { value: "list", icon: <List className="size-3.5" /> },
                            ]}
                            aria-label="分镜墙展示方式"
                        />
                    ) : null}
                </div>
            </div>

            {flatShots.length ? (
                <div className={mode === "grid" ? "grid gap-4 sm:grid-cols-2 xl:grid-cols-3" : "space-y-2"}>
                    {orderedShots.map((unit, index) => {
                        const candidates = assetsByUnit.get(unit.id) || [];
                        const activeJob = jobs.find((job) => job.unit_id === unit.id && isJobActive(job));
                        return (
                            <div
                                key={unit.id}
                                ref={(element) => {
                                    cardRefs.current.set(unit.id, element);
                                }}
                                className={mode === "list" ? "max-w-[720px]" : ""}
                            >
                                <ShotCard
                                    unit={unit}
                                    candidates={candidates}
                                    index={index}
                                    selected={selected.has(unit.id)}
                                    onSelect={(checked) => toggleSelect(unit.id, checked)}
                                    onGenerate={(capability) => void generate(unit, capability)}
                                    onUpload={(file) => void upload(unit, file)}
                                    onDropCard={(targetId) => void reorder(targetId)}
                                    onAttachAsset={(assetId) => void attachAsset(unit.id, assetId)}
                                    onReorder={() => undefined}
                                    busy={Boolean(activeJob)}
                                    progress={activeJob?.progress}
                                />
                            </div>
                        );
                    })}
                </div>
            ) : (
                <EmptyState
                    icon={<LayoutGrid className="size-6" />}
                    title="还没有分镜单元"
                    description="先添加镜头单元，或让 AI 根据稿件拆出第一版镜头结构。"
                    action={
                        <Button
                            variant="primary"
                            icon={<Plus className="size-3.5" />}
                            onClick={() => {
                                requestUnitCreate();
                                setStructureDrawer(true);
                            }}
                        >
                            添加镜头单元
                        </Button>
                    }
                    className="py-20"
                />
            )}

            <BatchGenerateModal
                open={batchOpen}
                unitIds={[...selected]}
                projectId={projectId}
                onClose={() => {
                    setBatchOpen(false);
                    setSelected(new Set());
                }}
            />
        </div>
    );
}
