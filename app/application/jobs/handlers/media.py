"""媒体 job handler：异步 provider（submit → poll → fetch）+ 相对 URI + 探测 + 缩略图。"""

import time

from app.integrations.media import build_media_provider
from app.store import UnitOfWork

from ..context import JobContext


def _provider(uow, capability: str):
    from app.application.providers import provider_for_capability

    return provider_for_capability(uow, capability)


def _asset_kind(capability: str) -> tuple[str, str]:
    if capability == "image":
        return "image/png", ".png"
    return "video/mp4", ".mp4"


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    capability = str(payload.get("capability") or "image")
    prompt = str(payload.get("prompt") or "")
    params = dict(payload.get("parameters") or {})
    with UnitOfWork(ctx.database) as uow:
        provider = _provider(uow, capability)
        project_id = ctx.job["project_id"]
        unit_id = ctx.job["unit_id"]
        media_store = ctx.media_store

    media_provider = build_media_provider(provider, capability)
    task_id = media_provider.submit(prompt, params)
    status, progress = media_provider.poll(task_id)
    while status not in ("done", "failed"):
        if ctx.should_cancel():
            raise JobCanceled()
        ctx.emit(f"{capability} 生成中 {int((progress or 0) * 100)}%", stage=capability, progress=progress)
        ctx.set_progress(progress or 0)
        time.sleep(2)
        status, progress = media_provider.poll(task_id)
    if status == "failed":
        raise RuntimeError(f"{capability} provider 返回失败")
    data = media_provider.fetch(task_id)
    mime_type, suffix = _asset_kind(capability)
    uri, sha256 = media_store.write_bytes(project_id, data, suffix, unit_id=unit_id)

    metadata: dict = {}
    thumb_uri = ""
    try:
        metadata = media_store.probe(uri)
        thumb_uri = media_store.make_thumb(uri, mime_type)
    except Exception as exc:
        ctx.emit(f"媒体探测/缩略图失败：{exc}", level="warn", stage=capability)

    if ctx.should_cancel():
        raise JobCanceled()
    with UnitOfWork(ctx.database) as uow:
        asset = uow.assets.create(
            {
                "project_id": project_id,
                "unit_id": unit_id,
                "kind": capability,
                "name": payload.get("name") or f"AI {capability}",
                "uri": uri,
                "thumb_uri": thumb_uri,
                "mime_type": mime_type,
                "sha256": sha256,
                "generation": {
                    "provider": provider["id"],
                    "prompt": prompt,
                    "parameters": params,
                    "task_id": task_id,
                },
                "metadata": metadata,
            }
        )
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={"asset_id": asset["id"]},
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"{capability} 素材已生成 {asset['id']}",
            stage=capability,
            progress=0.9,
        )
