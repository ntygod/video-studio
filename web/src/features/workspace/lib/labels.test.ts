import assert from "node:assert/strict";
import test from "node:test";

import { hasContentArtifact, isContentArtifactKind } from "./labels.ts";

test("项目元数据和制作流程产物不算真实内容稿件", () => {
    for (const kind of ["brief", "project_bible", "edit_plan", "timeline"]) {
        assert.equal(isContentArtifactKind(kind), false, kind);
    }
});

test("正文与开放类型仍可计入内容稿件", () => {
    for (const kind of ["outline", "script", "screenplay", "generated", "custom_kind"]) {
        assert.equal(isContentArtifactKind(kind), true, kind);
    }
});

test("仅有空时间线时不能完成形成稿件进度", () => {
    assert.equal(hasContentArtifact([{ kind: "brief" }, { kind: "project_bible" }, { kind: "timeline" }, { kind: "edit_plan" }]), false);
    assert.equal(hasContentArtifact([{ kind: "timeline" }, { kind: "script" }]), true);
});
