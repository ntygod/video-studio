/**
 * React Query 的 key 工厂。
 * <p>
 * 所有 query key 集中在这里定义，避免各处手写字符串数组导致 invalidate 打不中。
 * 约定：key 的第一段是资源名，后续段按"从大到小"的作用域排列，这样
 * invalidateQueries({queryKey: qk.artifactsRoot(pid)}) 能一次性命中该项目下所有单元的稿件。
 */

/** unit 作用域的归一化：undefined/null 表示"整个项目"。 */
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
    artifacts: (projectId: string, unitId?: string | null) => ["artifacts", projectId, scope(unitId)] as const,

    conversationsRoot: (projectId: string) => ["conversations", projectId] as const,
    conversations: (projectId: string, unitId?: string | null) => ["conversations", projectId, scope(unitId)] as const,
    conversation: (conversationId: string) => ["conversation", conversationId] as const,

    assetsRoot: (projectId: string) => ["assets", projectId] as const,
    assets: (projectId: string, unitId?: string | null) => ["assets", projectId, scope(unitId)] as const,

    jobsRoot: () => ["jobs"] as const,
    jobs: (projectId?: string) => ["jobs", projectId || "__all__"] as const,
    job: (jobId: string) => ["job", jobId] as const,

    providers: () => ["providers"] as const,
    capabilities: () => ["capabilities"] as const,
    workflows: () => ["workflows"] as const,
};
