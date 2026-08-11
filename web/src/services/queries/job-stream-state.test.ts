import assert from "node:assert/strict";
import test from "node:test";

import { applyJobStreamEvent } from "./job-stream-state.ts";

const baseJob = {
    id: "job-1",
    project_id: "project-1",
    unit_id: null,
    job_type: "llm",
    status: "running" as const,
    progress: 0.2,
    cancel_requested: false,
    payload: {},
    result: null,
    error: "",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    events: [],
};

test("任务事件按后端 id 去重", () => {
    const event = {
        id: "event-1",
        type: "job.event" as const,
        job_id: "job-1",
        level: "warning",
        stage: "retry",
        message: "准备重试",
        created_at: 1_700_000_001,
    };

    const once = applyJobStreamEvent(baseJob, event);
    const twice = applyJobStreamEvent(once, event);

    assert.equal(once.events?.length, 1);
    assert.equal(twice.events?.length, 1);
    assert.equal(twice.events?.[0].id, "event-1");
    assert.equal(twice.events?.[0].level, "warn");
});

test("后端秒级时间戳不会被再次除以 1000", () => {
    const updated = applyJobStreamEvent(baseJob, {
        type: "job.progress",
        job_id: "job-1",
        progress: 0.8,
        created_at: 1_700_000_123,
    });

    assert.equal(updated.updated_at, 1_700_000_123);
    assert.equal(updated.progress, 0.8);
});
