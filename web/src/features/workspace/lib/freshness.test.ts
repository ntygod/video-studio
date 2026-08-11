import assert from "node:assert/strict";
import test from "node:test";

import type {
    ProjectArtifactFreshness,
    ProjectArtifactFreshnessItem,
} from "@/services/api";
import {
    actionableFreshnessCount,
    freshnessByUnit,
    sortFreshnessItems,
} from "./freshness.ts";

function item(
    artifactId: string,
    status: ProjectArtifactFreshnessItem["status"],
    unitId: string | null,
    updatedAt: number,
): ProjectArtifactFreshnessItem {
    return {
        artifact_id: artifactId,
        project_id: "project-1",
        unit_id: unitId,
        kind: "generated",
        name: artifactId,
        current_version_id: `${artifactId}-v1`,
        status,
        reason: "",
        stale_from_version_ids: [],
        blocked_by_asset_ids: [],
        detected_at: updatedAt,
        updated_at: updatedAt,
    };
}

test("actionable count excludes fresh Artifacts", () => {
    const data: ProjectArtifactFreshness = {
        counts: {
            fresh: 8,
            stale: 2,
            blocked: 1,
            needs_review: 3,
        },
        items: [],
    };
    assert.equal(actionableFreshnessCount(data), 6);
});

test("unit summary keeps the most severe state and total count", () => {
    const summary = freshnessByUnit([
        item("a", "stale", "unit-1", 1),
        item("b", "blocked", "unit-1", 2),
        item("c", "needs_review", "unit-2", 3),
        item("d", "fresh", "unit-2", 4),
        item("project", "blocked", null, 5),
    ]);
    assert.deepEqual(summary.get("unit-1"), {
        status: "blocked",
        count: 2,
    });
    assert.deepEqual(summary.get("unit-2"), {
        status: "needs_review",
        count: 1,
    });
    assert.equal(summary.size, 2);
});

test("freshness ordering is severity then recency then stable id", () => {
    const sorted = sortFreshnessItems([
        item("stale-old", "stale", null, 1),
        item("review", "needs_review", null, 9),
        item("blocked-b", "blocked", null, 4),
        item("blocked-a", "blocked", null, 4),
        item("stale-new", "stale", null, 8),
    ]);
    assert.deepEqual(
        sorted.map((entry) => entry.artifact_id),
        [
            "blocked-a",
            "blocked-b",
            "stale-new",
            "stale-old",
            "review",
        ],
    );
});
