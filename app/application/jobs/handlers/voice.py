"""批量配音 job handler：逐条 edge-tts 合成，全部落为 voice assets。"""

from pathlib import Path

from app.application.voice_service import synthesize_lines
from app.store import UnitOfWork

from ..context import JobContext


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    lines = payload.get("lines") or []
    with UnitOfWork(ctx.database) as uow:
        job = uow.jobs.get(ctx.job["id"])
        project_id = job["project_id"]
        unit_id = job["unit_id"]
    total = max(len(lines), 1)
    assets = synthesize_lines(ctx.settings, ctx.database, project_id, unit_id, lines)
    if ctx.should_cancel():
        raise JobCanceled()
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={"asset_ids": [asset["id"] for asset in assets], "count": len(assets)},
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"已合成 {len(assets)} 条声音",
            stage="voice",
            progress=0.9,
        )
