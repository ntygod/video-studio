"""渲染 job handler：时间线 → ffmpeg，进度实时写事件（0% 不再直接跳 100%）。"""

from pathlib import Path

from app.application.timeline_render import render_timeline
from app.store import UnitOfWork

from ..context import JobContext


def _relative_uri(settings, absolute_path: str) -> str:
    return Path(absolute_path).resolve().relative_to(settings.media_dir.resolve()).as_posix()


def _resolve_asset(ctx, asset_id: str) -> str:
    """clip.asset_id 是素材 id（T4.1）；查不到时按旧版相对 uri 兼容解析。"""
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
    timeline = payload.get("timeline") or {}
    with UnitOfWork(ctx.database) as uow:
        job = uow.jobs.get(ctx.job["id"])
        project_id = job["project_id"]
        unit_id = job["unit_id"]

    def on_progress(ratio: float) -> None:
        ctx.set_progress(ratio * 0.9)

    output_abs, duration = render_timeline(
        ctx.settings,
        project_id,
        timeline,
        progress=on_progress,
        should_cancel=ctx.should_cancel,
        asset_resolver=lambda asset_id: _resolve_asset(ctx, asset_id),
    )
    uri = _relative_uri(ctx.settings, output_abs)
    metadata: dict = {"duration": duration}
    thumb_uri = ""
    try:
        metadata = ctx.media_store.probe(uri)
        thumb_uri = ctx.media_store.make_thumb(uri, "video/mp4")
    except Exception as exc:
        ctx.emit(f"渲染探测/缩略图失败：{exc}", level="warn", stage="render")
    if ctx.should_cancel():
        raise JobCanceled()
    with UnitOfWork(ctx.database) as uow:
        asset = uow.assets.create(
            {
                "project_id": project_id,
                "unit_id": unit_id,
                "kind": "render",
                "name": payload.get("name") or "成片",
                "uri": uri,
                "thumb_uri": thumb_uri,
                "mime_type": "video/mp4",
                "sha256": "",
                "generation": {"timeline": timeline},
                "metadata": metadata,
            }
        )
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.95,
            result={"asset_id": asset["id"], "uri": uri, "duration": duration},
        )
        uow.jobs.add_event(
            ctx.job["id"], f"成片已渲染 {asset['id']}", stage="render", progress=0.95
        )
