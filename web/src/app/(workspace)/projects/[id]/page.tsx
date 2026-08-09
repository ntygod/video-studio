import { redirect } from "next/navigation";

import { DEFAULT_CANVAS_VIEW } from "@/features/workspace/stores/use-workspace-store";

/**
 * 项目根路径重定向到默认视图。
 * <p>
 * 保留 ?unit= 参数，避免从别处跳进来时丢掉选中的创作单元。
 */
export default async function ProjectIndexPage({
    params,
    searchParams,
}: {
    params: Promise<{ id: string }>;
    searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
    const { id } = await params;
    const query = await searchParams;
    const unit = typeof query.unit === "string" ? query.unit : undefined;
    const suffix = unit ? `?unit=${encodeURIComponent(unit)}` : "";

    redirect(`/projects/${encodeURIComponent(id)}/${DEFAULT_CANVAS_VIEW}${suffix}`);
}
