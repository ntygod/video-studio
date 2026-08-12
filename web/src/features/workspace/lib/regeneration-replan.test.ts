import assert from "node:assert/strict";
import test from "node:test";

import type {
    RegenerationPlan,
    RegenerationPlanLineage,
} from "@/services/api";
import {
    isRegenerationReplanSourceStatus,
    regenerationPlanReplanBlocker,
} from "./regeneration-replan.ts";

const canceledPlan = {
    id: "source-plan",
    status: "canceled",
    root_artifact_ids: ["root"],
    steps: [
        {
            status: "canceled",
            claimed: false,
        },
    ],
} as RegenerationPlan;

test("replan accepts settled non-successful sources", () => {
    assert.equal(isRegenerationReplanSourceStatus("draft"), true);
    assert.equal(isRegenerationReplanSourceStatus("failed"), true);
    assert.equal(isRegenerationReplanSourceStatus("running"), false);
    assert.equal(regenerationPlanReplanBlocker(canceledPlan), null);
});

test("replan blocks active work and an existing child", () => {
    assert.equal(
        regenerationPlanReplanBlocker({
            ...canceledPlan,
            steps: [{ status: "queued", claimed: false }],
        } as RegenerationPlan),
        "仍有子任务或步骤租约尚未结束",
    );
    assert.equal(
        regenerationPlanReplanBlocker(
            canceledPlan,
            {
                plan_id: "source-plan",
                project_id: "project",
                replanned_from: null,
                replanned_by: {
                    id: "relation",
                    project_id: "project",
                    source_plan_id: "source-plan",
                    target_plan_id: "target-plan",
                    source_status: "canceled",
                    source_execution_attempt: 0,
                    target_snapshot_sha256: "snapshot",
                    reason: "changed graph",
                    created_at: 1,
                },
            } as RegenerationPlanLineage,
        ),
        "已经重新规划为 target-p",
    );
});
