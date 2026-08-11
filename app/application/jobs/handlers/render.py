"""Render Job handler with recoverable generated-file persistence."""

from pathlib import Path

from app.application.commands import (
    CommandBus, CommandContext, PersistGeneratedFileAssetCommand,
    job_asset_persistence_attempt,
)
from app.application.timeline_render import render_timeline
from app.store import UnitOfWork

from ..context import JobContext


def _relative_uri(settings, absolute_path: str) -> str:
    return Path(absolute_path).resolve().relative_to(settings.media_dir.resolve()).as_posix()


def _resolve_asset(ctx, asset_id: str) -> str:
    with UnitOfWork(ctx.database) as uow:
        try:
            asset = uow.assets.get(asset_id)
            return str((ctx.settings.media_dir / asset["uri"]).resolve())
        except Exception:
            from app.application.timeline_render import _resolve
            return _resolve(ctx.settings, asset_id)


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled
    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    existing, key = job_asset_persistence_attempt(ctx.database, ctx.job["id"])
    if existing is not None:
        asset = existing
        duration = float((asset.get("metadata") or {}).get("duration") or 0.0)
    else:
        timeline = payload.get("timeline") or {}
        with UnitOfWork(ctx.database) as uow:
            job = uow.jobs.get(ctx.job["id"])
            project_id, unit_id = job["project_id"], job["unit_id"]
        output_abs, duration = render_timeline(
            ctx.settings, project_id, timeline,
            progress=lambda ratio: ctx.set_progress(ratio * 0.9),
            should_cancel=ctx.should_cancel,
            asset_resolver=lambda asset_id: _resolve_asset(ctx, asset_id),
        )
        source_uri = _relative_uri(ctx.settings, output_abs)
        if ctx.should_cancel():
            ctx.media_store.delete_asset(source_uri)
            raise JobCanceled()
        asset = CommandBus(ctx.database).execute(
            PersistGeneratedFileAssetCommand(
                project_id=project_id, unit_id=unit_id,
                source_uri=source_uri, media_store=ctx.media_store,
                kind="render", name=payload.get("name") or "成片",
                mime_type="video/mp4",
                generation={
                    "source": "timeline-render", "timeline": timeline,
                    "job_id": ctx.job["id"],
                },
                metadata={"duration": duration},
            ),
            CommandContext(
                actor_type="job", actor_id=ctx.job["id"],
                request_id=str(payload.get("_request_id") or ""),
                turn_id=str(job.get("turn_id") or ""),
                idempotency_key=key,
            ),
        ).result
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"], "running", progress=0.95,
            result={
                "asset_id": asset["id"], "uri": asset["uri"],
                "duration": duration,
            },
        )
        uow.jobs.add_event(
            ctx.job["id"], f"成片已渲染 {asset['id']}",
            stage="render", progress=0.95,
        )
