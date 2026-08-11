"""批量生成父任务：子任务完成比例即父任务进度。"""

import time

from app.store import UnitOfWork

from ..context import JobContext


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    payload = ctx.job.get("payload") or {}
    child_ids = payload.get("child_job_ids") or []
    total = max(len(child_ids), 1)
    while True:
        if ctx.should_cancel():
            raise JobCanceled()
        done = 0
        warnings = []
        with UnitOfWork(ctx.database) as uow:
            for child_id in child_ids:
                child = uow.jobs.get(child_id)
                if child["status"] in ("succeeded", "failed", "canceled"):
                    done += 1
                if child["status"] in ("failed", "canceled"):
                    warnings.append(f"子任务 {child_id[:8]} {child['status']}")
        for warning in warnings:
            ctx.emit(warning, level="warn", stage="batch")
        progress = done / total
        ctx.set_progress(progress)
        if done >= total:
            break
        time.sleep(1)
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=1.0,
            result={"child_count": len(child_ids), "done": done},
        )
        uow.jobs.add_event(
            ctx.job["id"], f"批量生成完成 {done}/{total}", stage="batch", progress=1.0
        )
