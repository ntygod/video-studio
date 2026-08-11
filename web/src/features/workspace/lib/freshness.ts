import type {
    ArtifactFreshnessStatus,
    ProjectArtifactFreshness,
    ProjectArtifactFreshnessItem,
} from "@/services/api";

export type FreshnessTone =
    | "success"
    | "warning"
    | "danger"
    | "info";

export type FreshnessDotTone =
    | "success"
    | "warning"
    | "error"
    | "active";

export type FreshnessMeta = {
    label: string;
    shortLabel: string;
    tone: FreshnessTone;
    dotTone: FreshnessDotTone;
    severity: number;
};

const META: Record<ArtifactFreshnessStatus, FreshnessMeta> = {
    fresh: {
        label: "内容为最新",
        shortLabel: "最新",
        tone: "success",
        dotTone: "success",
        severity: 0,
    },
    needs_review: {
        label: "需要人工审阅",
        shortLabel: "待审阅",
        tone: "info",
        dotTone: "active",
        severity: 1,
    },
    stale: {
        label: "上游已更新，需要重新生成",
        shortLabel: "已过期",
        tone: "warning",
        dotTone: "warning",
        severity: 2,
    },
    blocked: {
        label: "必需输入缺失，暂时无法继续",
        shortLabel: "已阻塞",
        tone: "danger",
        dotTone: "error",
        severity: 3,
    },
};

export type UnitFreshnessSummary = {
    status: ArtifactFreshnessStatus;
    count: number;
};

export function freshnessMeta(
    status: ArtifactFreshnessStatus,
): FreshnessMeta {
    return META[status];
}

export function isActionableFreshness(
    status: ArtifactFreshnessStatus,
): boolean {
    return status !== "fresh";
}

export function actionableFreshnessCount(
    data?: ProjectArtifactFreshness,
): number {
    if (!data) return 0;
    return (
        data.counts.stale +
        data.counts.blocked +
        data.counts.needs_review
    );
}

export function freshnessByArtifact(
    items: ReadonlyArray<ProjectArtifactFreshnessItem>,
): Map<string, ProjectArtifactFreshnessItem> {
    return new Map(
        items.map((item) => [item.artifact_id, item])
    );
}

export function freshnessByUnit(
    items: ReadonlyArray<ProjectArtifactFreshnessItem>,
): Map<string, UnitFreshnessSummary> {
    const result = new Map<string, UnitFreshnessSummary>();
    for (const item of items) {
        if (!item.unit_id || !isActionableFreshness(item.status)) {
            continue;
        }
        const current = result.get(item.unit_id);
        if (!current) {
            result.set(item.unit_id, {
                status: item.status,
                count: 1,
            });
            continue;
        }
        const status =
            freshnessMeta(item.status).severity >
            freshnessMeta(current.status).severity
                ? item.status
                : current.status;
        result.set(item.unit_id, {
            status,
            count: current.count + 1,
        });
    }
    return result;
}

export function sortFreshnessItems(
    items: ReadonlyArray<ProjectArtifactFreshnessItem>,
): ProjectArtifactFreshnessItem[] {
    return [...items].sort((left, right) => {
        const severity =
            freshnessMeta(right.status).severity -
            freshnessMeta(left.status).severity;
        if (severity !== 0) return severity;
        if (right.updated_at !== left.updated_at) {
            return right.updated_at - left.updated_at;
        }
        return left.artifact_id.localeCompare(right.artifact_id);
    });
}
