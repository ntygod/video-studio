import type {
    Asset,
    RegenerationPlan,
    RegenerationPlanStepStatus,
    RegenerationPlanStatus,
    RegenerationPreviewAction,
} from "@/services/api";
import type { ChipTone } from "@/shared/ui/chip";

export type RegenerationStatusMeta = {
    label: string;
    tone: ChipTone;
    dotTone: "success" | "warning" | "error" | "active";
};

const PLAN_META: Record<RegenerationPlanStatus, RegenerationStatusMeta> = {
    draft: {
        label: "待开始",
        tone: "default",
        dotTone: "active",
    },
    running: {
        label: "执行中",
        tone: "info",
        dotTone: "active",
    },
    blocked: {
        label: "需处理",
        tone: "warning",
        dotTone: "warning",
    },
    succeeded: {
        label: "已完成",
        tone: "success",
        dotTone: "success",
    },
    failed: {
        label: "失败",
        tone: "danger",
        dotTone: "error",
    },
    canceled: {
        label: "已取消",
        tone: "default",
        dotTone: "warning",
    },
};

const STEP_META: Record<
    RegenerationPlanStepStatus,
    RegenerationStatusMeta
> = {
    ready: {
        label: "可执行",
        tone: "accent",
        dotTone: "active",
    },
    waiting_for_predecessors: {
        label: "等待前序",
        tone: "info",
        dotTone: "active",
    },
    requires_input: {
        label: "需要输入",
        tone: "warning",
        dotTone: "warning",
    },
    requires_review: {
        label: "需要审阅",
        tone: "info",
        dotTone: "active",
    },
    manual: {
        label: "需手工处理",
        tone: "warning",
        dotTone: "warning",
    },
    blocked: {
        label: "已阻塞",
        tone: "danger",
        dotTone: "error",
    },
    skipped: {
        label: "无需处理",
        tone: "default",
        dotTone: "success",
    },
    queued: {
        label: "已排队",
        tone: "info",
        dotTone: "active",
    },
    running: {
        label: "执行中",
        tone: "info",
        dotTone: "active",
    },
    succeeded: {
        label: "已完成",
        tone: "success",
        dotTone: "success",
    },
    failed: {
        label: "失败",
        tone: "danger",
        dotTone: "error",
    },
    canceled: {
        label: "已取消",
        tone: "default",
        dotTone: "warning",
    },
};

const ACTION_LABEL: Record<RegenerationPreviewAction, string> = {
    none: "保持当前版本",
    regenerate_llm: "按最新输入重新生成",
    recompile_timeline: "重新编译时间线",
    repair_timeline_assets: "替换素材并重编译",
    review: "人工审阅",
    manual: "手工修复",
};

const VISUAL_KINDS = new Set(["image", "video"]);

export function regenerationPlanMeta(
    status: RegenerationPlanStatus,
): RegenerationStatusMeta {
    return PLAN_META[status];
}

export function regenerationStepMeta(
    status: RegenerationPlanStepStatus,
): RegenerationStatusMeta {
    return STEP_META[status];
}

export function regenerationActionLabel(
    action: RegenerationPreviewAction,
): string {
    return ACTION_LABEL[action];
}

export function isRegenerationPlanTerminal(
    status: RegenerationPlanStatus,
): boolean {
    return ["succeeded", "failed", "canceled"].includes(status);
}

export function regenerationPlanHasUnresolvedInput(
    plan?: RegenerationPlan | null,
): boolean {
    return Boolean(
        plan?.steps?.some((step) => step.status === "requires_input"),
    );
}

export function compatibleReplacementAsset(
    snapshot: Partial<Asset>,
    candidate: Asset,
): boolean {
    const oldKind = String(snapshot.kind || "");
    const sameKind = oldKind === candidate.kind;
    const visualSwap =
        VISUAL_KINDS.has(oldKind) && VISUAL_KINDS.has(candidate.kind);
    return (
        (sameKind || visualSwap) &&
        (snapshot.unit_id ?? null) === candidate.unit_id
    );
}
