"use client";

import { useCallback, useMemo } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";

import { normalizeCanvasView, type CanvasView } from "@/features/workspace/stores/use-workspace-store";

/** 选中单元在 URL 上的参数名。 */
const UNIT_PARAM = "unit";

type WorkspaceRoute = {
    projectId: string;
    /** 当前画布视图，来自路由末段。 */
    view: CanvasView;
    /** 当前选中的创作单元；null 表示"整个项目"。 */
    selectedUnitId: string | null;
    /** 切换视图，保留当前选中单元。 */
    setView: (view: CanvasView) => void;
    /** 切换选中单元，保留当前视图。传 null 回到整个项目。 */
    setSelectedUnit: (unitId: string | null) => void;
    /** 生成指定视图的链接，供 Link 组件使用。 */
    hrefFor: (view: CanvasView, unitId?: string | null) => string;
};

/**
 * 工作台的路由状态。
 * <p>
 * 视图与选中单元都存在 URL 上（/projects/{id}/{view}?unit={unitId}），
 * 这样刷新、后退、分享链接都能恢复到同一个位置——旧实现把这两者放在组件 state 里，刷新即丢。
 *
 * @return WorkspaceRoute 当前路由状态与导航方法
 */
export function useWorkspaceRoute(): WorkspaceRoute {
    const params = useParams<{ id: string; view?: string | string[] }>();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const router = useRouter();

    const projectId = String(params?.id || "");

    // 视图取路径最后一段，比读 params.view 更稳（不依赖动态段的命名）。
    const view = useMemo(() => {
        const segments = pathname.split("/").filter(Boolean);
        return normalizeCanvasView(segments[segments.length - 1]);
    }, [pathname]);

    const selectedUnitId = searchParams.get(UNIT_PARAM) || null;

    const hrefFor = useCallback(
        (targetView: CanvasView, unitId?: string | null) => {
            const nextUnit = unitId === undefined ? selectedUnitId : unitId;
            const query = nextUnit ? `?${UNIT_PARAM}=${encodeURIComponent(nextUnit)}` : "";
            return `/projects/${encodeURIComponent(projectId)}/${targetView}${query}`;
        },
        [projectId, selectedUnitId],
    );

    const setView = useCallback(
        (targetView: CanvasView) => {
            router.push(hrefFor(targetView));
        },
        [hrefFor, router],
    );

    const setSelectedUnit = useCallback(
        (unitId: string | null) => {
            // 用 replace：切换单元是浏览行为，不该在后退栈里堆积。
            router.replace(hrefFor(view, unitId));
        },
        [hrefFor, router, view],
    );

    return { projectId, view, selectedUnitId, setView, setSelectedUnit, hrefFor };
}
