/**
 * React Query 的 key 工厂。
 * <p>
 * 所有 query key 集中在这里定义，避免各处手写字符串数组导致 invalidate 打不中。
 * 约定：key 的第一段是资源名，后续段按"从大到小"的作用域排列。
 */

function scope(unitId?: string | null): string {
    return unitId || "__project__";
}

export const qk = {
    health: () => ["health"] as const,

    projects: () => ["projects"] as const,
    project: (projectId: string) => ["project", projectId] as const,

    unitsRoot: (projectId: string) => ["units", projectId] as const,
    units: (projectId: string, parentId?: string | null) => ["units", projectId, scope(parentId)] as const,

    artifactsRoot: (projectId: string) => ["artifacts", projectId] as const,
    proposalsRoot: (projectId: string) => ["proposals", projectId] as const,
    artifacts: (projectId: string, unitId?: string | null) => ["artifacts", projectId, scope(unitId)] as const,

    freshnessRoot: (projectId: string) => ["artifact-freshness", projectId] as const,
    freshness: (projectId: string, includeFresh = false) =>
        ["artifact-freshness", projectId, includeFresh ? "all" : "actionable"] as const,
    artifactImpact: (artifactId: string) => ["artifact-impact", artifactId] as const,
    artifactAssetDependencies: (artifactId: string) =>
        ["artifact-asset-dependencies", artifactId] as const,
    regenerationPlansRoot: (projectId: string) =>
        ["regeneration-plans", projectId] as const,
    regenerationPlan: (planId: string) =>
        ["regeneration-plan", planId] as const,
    regenerationPlanLineage: (planId: string) =>
        ["regeneration-plan-lineage", planId] as const,

    conversationsRoot: (projectId: string) => ["conversations", projectId] as const,
    conversations: (projectId: string, unitId?: string | null) => ["conversations", projectId, scope(unitId)] as const,
    conversation: (conversationId: string) => ["conversation", conversationId] as const,

    assetsRoot: (projectId: string) => ["assets", projectId] as const,
    assets: (projectId: string, unitId?: string | null) => ["assets", projectId, scope(unitId)] as const,

    jobsRoot: () => ["jobs"] as const,
    jobs: (projectId?: string) => ["jobs", projectId || "__all__"] as const,
    job: (jobId: string) => ["job", jobId] as const,

    search: (projectId: string) => ["search", projectId] as const,

    providers: () => ["providers"] as const,
    capabilities: () => ["capabilities"] as const,
};
