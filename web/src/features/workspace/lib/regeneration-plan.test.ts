import assert from "node:assert/strict";
import test from "node:test";

import type { Asset, RegenerationPlan } from "@/services/api";
import {
    compatibleReplacementAsset,
    isRegenerationPlanTerminal,
    regenerationActionLabel,
    regenerationPlanHasUnresolvedInput,
    regenerationPlanMeta,
    regenerationStepMeta,
} from "./regeneration-plan.ts";

function asset(
    id: string,
    kind: string,
    unitId: string | null,
): Asset {
    return {
        id,
        project_id: "project-1",
        unit_id: unitId,
        shot_id: null,
        kind,
        name: id,
        uri: `${id}.bin`,
        thumb_uri: "",
        mime_type: "application/octet-stream",
        sha256: "",
        parent_asset_id: null,
        generation: {},
        metadata: {},
        created_at: 1,
    };
}

test("regeneration plan labels cover runtime states", () => {
    assert.equal(regenerationPlanMeta("running").label, "执行中");
    assert.equal(regenerationStepMeta("queued").label, "已排队");
    assert.equal(
        regenerationActionLabel("repair_timeline_assets"),
        "替换素材并重编译",
    );
    assert.equal(isRegenerationPlanTerminal("succeeded"), true);
    assert.equal(isRegenerationPlanTerminal("blocked"), false);
});

test("replacement compatibility preserves scope and media family", () => {
    const snapshot = { kind: "image", unit_id: "unit-1" };
    assert.equal(
        compatibleReplacementAsset(
            snapshot,
            asset("video", "video", "unit-1"),
        ),
        true,
    );
    assert.equal(
        compatibleReplacementAsset(
            snapshot,
            asset("voice", "voice", "unit-1"),
        ),
        false,
    );
    assert.equal(
        compatibleReplacementAsset(
            snapshot,
            asset("other-unit", "image", "unit-2"),
        ),
        false,
    );
});

test("unresolved structured input prevents starting a draft plan", () => {
    const plan = {
        status: "draft",
        steps: [
            { status: "requires_input" },
            { status: "ready" },
        ],
    } as RegenerationPlan;
    assert.equal(regenerationPlanHasUnresolvedInput(plan), true);
    assert.equal(
        regenerationPlanHasUnresolvedInput({
            ...plan,
            steps: [{ status: "ready" }],
        } as RegenerationPlan),
        false,
    );
});
