"use client";

import { useMemo } from "react";

import type { Artifact, Asset, CreativeUnit, ProjectDetail, Proposal } from "@/services/api";
import { useArtifacts, useAssets, useProject, useProposals, useUnits } from "@/services/queries";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { isContentArtifactKind, META_ARTIFACT_KINDS } from "@/features/workspace/lib/labels";

/** 单元树节点：在原始单元上挂 children 与层级。 */
export type UnitNode = CreativeUnit & {
    children: UnitNode[];
    depth: number;
};

/**
 * 把扁平单元列表组装成树。
 * <p>
 * 后端返回的是扁平数组 + parent_id，父节点缺失（例如被删除）的单元会被提升到根级，
 * 避免整棵子树在界面上凭空消失。
 *
 * @param units CreativeUnit[] 扁平单元列表
 * @return UnitNode[] 根级节点数组，已按 order_index 排序
 */
export function buildUnitTree(units: CreativeUnit[]): UnitNode[] {
    const nodes = new Map<string, UnitNode>();
    units.forEach((unit) => nodes.set(unit.id, { ...unit, children: [], depth: 0 }));

    const roots: UnitNode[] = [];
    nodes.forEach((node) => {
        const parent = node.parent_id ? nodes.get(node.parent_id) : undefined;
        if (parent) parent.children.push(node);
        else roots.push(node);
    });

    const sortByOrder = (list: UnitNode[], depth: number) => {
        list.sort((a, b) => a.order_index - b.order_index || a.created_at - b.created_at);
        list.forEach((node) => {
            node.depth = depth;
            sortByOrder(node.children, depth + 1);
        });
    };
    sortByOrder(roots, 0);

    return roots;
}

/** 按前序遍历把单元树摊平，供虚拟化列表使用。 */
export function flattenUnitTree(nodes: UnitNode[], collapsed?: Set<string>): UnitNode[] {
    const result: UnitNode[] = [];
    const walk = (list: UnitNode[]) => {
        list.forEach((node) => {
            result.push(node);
            if (!collapsed?.has(node.id)) walk(node.children);
        });
    };
    walk(nodes);
    return result;
}

type WorkspaceData = {
    projectId: string;
    project: ProjectDetail | undefined;
    isLoading: boolean;
    error: Error | null;
    selectedUnitId: string | null;
    /** 当前选中的单元对象；null 表示作用于整个项目。 */
    selectedUnit: CreativeUnit | null;
    /** 全部单元（扁平）。 */
    units: CreativeUnit[];
    /** 单元树。 */
    unitTree: UnitNode[];
    /** 供 Select 使用的单元选项。 */
    unitOptions: Array<{ value: string; label: string }>;
    /** 全部稿件（含 brief / project_bible，T3.1 后由分页接口组装）。 */
    artifacts: Artifact[];
    /** 当前作用域下可进入版本审阅的稿件（排除项目内建元数据）。 */
    reviewableArtifacts: Artifact[];
    /** 当前作用域下的真实内容稿件（再排除时间线、剪辑计划等制作产物）。 */
    contentArtifacts: Artifact[];
    /** 当前作用域下的待处理提案。 */
    pendingProposals: Proposal[];
    /** 当前作用域下的素材。 */
    assets: Asset[];
    assetsLoading: boolean;
    /** 项目是否已有可用的角色/世界/风格设定。 */
    hasBibleContent: boolean;
    /** 当前作用域下是否已有剪辑方案。 */
    hasEditPlan: boolean;
};

/**
 * 工作台共享数据（T3.1 重构）。
 * <p>
 * 项目详情已瘦身：单元/稿件/提案各自走分页接口并在此组装。
 * 所有派生值都走 useMemo，切换单元不会重新请求项目。
 */
export function useWorkspaceData(): WorkspaceData {
    const { projectId, selectedUnitId } = useWorkspaceRoute();
    const projectQuery = useProject(projectId);
    const unitsQuery = useUnits(projectId);
    const artifactsQuery = useArtifacts(projectId, null, true);
    const proposalsQuery = useProposals(projectId);
    const assetsQuery = useAssets(projectId, selectedUnitId);

    const project = projectQuery.data;
    const units = useMemo(() => unitsQuery.data || [], [unitsQuery.data]);

    const unitTree = useMemo(() => buildUnitTree(units), [units]);

    const selectedUnit = useMemo(() => (selectedUnitId ? units.find((unit) => unit.id === selectedUnitId) || null : null), [selectedUnitId, units]);

    const unitOptions = useMemo(
        () =>
            flattenUnitTree(unitTree).map((unit) => ({
                value: unit.id,
                label: `${"　".repeat(unit.depth)}${unit.title}`,
            })),
        [unitTree],
    );

    const inScope = useMemo(() => (unitId: string | null) => !selectedUnitId || unitId === selectedUnitId, [selectedUnitId]);

    const artifacts = useMemo(() => artifactsQuery.data || [], [artifactsQuery.data]);

    const reviewableArtifacts = useMemo(() => artifacts.filter((artifact) => !META_ARTIFACT_KINDS.includes(artifact.kind) && inScope(artifact.unit_id)), [artifacts, inScope]);

    const contentArtifacts = useMemo(() => reviewableArtifacts.filter((artifact) => isContentArtifactKind(artifact.kind)), [reviewableArtifacts]);

    const pendingProposals = useMemo(() => (proposalsQuery.data || []).filter((proposal) => inScope(proposal.unit_id)), [proposalsQuery.data, inScope]);

    const hasEditPlan = useMemo(() => artifacts.some((artifact) => artifact.kind === "edit_plan" && inScope(artifact.unit_id)), [artifacts, inScope]);

    const hasBibleContent = useMemo(() => {
        const bible = project?.bible;
        if (!bible) return false;
        return Boolean(
            bible.logline ||
            bible.long_arc ||
            bible.themes.length ||
            bible.characters.length ||
            bible.world.premise ||
            bible.world.era ||
            bible.world.locations.length ||
            bible.world.rules.length ||
            bible.style.visual_direction ||
            bible.style.sound_direction,
        );
    }, [project?.bible]);

    return {
        projectId,
        project,
        isLoading: projectQuery.isLoading || unitsQuery.isLoading,
        error: projectQuery.error || unitsQuery.error || null,
        selectedUnitId,
        selectedUnit,
        units,
        unitTree,
        unitOptions,
        artifacts,
        reviewableArtifacts,
        contentArtifacts,
        pendingProposals,
        assets: assetsQuery.data || [],
        assetsLoading: assetsQuery.isLoading,
        hasBibleContent,
        hasEditPlan,
    };
}
