import type {
    RegenerationPlan,
    RegenerationPlanLineage,
    RegenerationReplanSourceStatus,
} from "@/services/api";

const REPLAN_SOURCE_STATUSES = new Set<RegenerationReplanSourceStatus>([
    "draft",
    "blocked",
    "failed",
    "canceled",
]);

export function isRegenerationReplanSourceStatus(
    status: RegenerationPlan["status"],
): status is RegenerationReplanSourceStatus {
    return REPLAN_SOURCE_STATUSES.has(
        status as RegenerationReplanSourceStatus,
    );
}

export function regenerationPlanReplanBlocker(
    plan?: RegenerationPlan | null,
    lineage?: RegenerationPlanLineage | null,
): string | null {
    if (!plan) return "修复计划尚未加载";
    if (lineage?.replanned_by) {
        return `已经重新规划为 ${lineage.replanned_by.target_plan_id.slice(0, 8)}`;
    }
    if (!isRegenerationReplanSourceStatus(plan.status)) {
        return plan.status === "running"
            ? "先停止当前执行，再重新规划"
            : "已成功完成的计划不需要重新规划";
    }
    if (!plan.root_artifact_ids.length) {
        return "计划没有可重新规划的根内容";
    }
    if (
        plan.steps?.some(
            (step) =>
                step.status === "queued" ||
                step.status === "running" ||
                step.claimed,
        )
    ) {
        return "仍有子任务或步骤租约尚未结束";
    }
    return null;
}
