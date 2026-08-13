import threading
import time

from app.application.commands import CommandBus, CommandContext, CreateJobCommand
from app.application.job_engine import JobEngine
from app.application.jobs.runtime_contract import MEDIA_JOB_PLAN_KIND
from app.application.jobs.runtime_executor_patch import _execute_runtime_job
from app.application.task_runtime_engine import TaskExecutionContext
from app.store import UnitOfWork


def test_runtime_job_replays_completed_job_after_attempt_lease_loss(app, project):
    job = CommandBus(app.state.database).execute(
        CreateJobCommand(
            project_id=project["id"],
            job_type="media",
            payload={
                "capability": "image",
                "prompt": "雨夜街头",
                "parameters": {},
            },
        ),
        CommandContext(idempotency_key="runtime-media-crash-window"),
    ).result
    engine = JobEngine(
        app.state.database,
        app.state.settings,
        app.state.media_store,
        workers=1,
    )
    calls: list[str] = []

    def fake_handler(ctx):
        calls.append(ctx.job["id"])
        with UnitOfWork(app.state.database) as uow:
            uow.jobs.update_state(
                ctx.job["id"],
                "running",
                progress=0.9,
                result={"asset_id": "asset-once"},
            )

    engine._handler_for = lambda _job: fake_handler
    runtime = engine._durable_job_engine.runtime
    claimed_at = time.time()
    first = runtime.claim_next(
        "runtime-worker-1",
        kinds={MEDIA_JOB_PLAN_KIND},
        lease_seconds=1,
        now=claimed_at,
    )
    assert first is not None
    first_context = TaskExecutionContext.from_claim(
        runtime,
        first,
        1,
        threading.Event(),
    )
    first_result = _execute_runtime_job(engine, first_context)
    assert first_result["replayed"] is False
    assert calls == [job["id"]]

    recovered = runtime.recover(
        kinds={MEDIA_JOB_PLAN_KIND},
        now=claimed_at + 2,
    )
    assert recovered >= 1
    second = runtime.claim_next(
        "runtime-worker-2",
        kinds={MEDIA_JOB_PLAN_KIND},
        lease_seconds=30,
        now=claimed_at + 2,
    )
    assert second is not None
    second_context = TaskExecutionContext.from_claim(
        runtime,
        second,
        30,
        threading.Event(),
    )
    replayed = _execute_runtime_job(engine, second_context)
    assert replayed["replayed"] is True
    assert calls == [job["id"]]
    runtime.complete(
        second,
        result=replayed,
        checkpoint=second_context.checkpoint,
        usage=second_context.usage,
        now=claimed_at + 2.1,
    )

    with UnitOfWork(app.state.database) as uow:
        saved = uow.jobs.get(job["id"])
        plan = uow.task_runtime.get_plan(job["runtime_plan_id"])
    assert saved["status"] == "succeeded"
    assert saved["result"] == {"asset_id": "asset-once"}
    assert plan["status"] == "succeeded"
