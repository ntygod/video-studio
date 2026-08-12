"""Media provider handler with recoverable, idempotent Asset persistence."""

import time

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedAssetCommand,
    job_asset_persistence_attempt,
)
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


def _ids(payload: dict, key: str) -> list[str]:
    return [
        value
        for item in payload.get(key) or []
        if (value := str(item or ""))
    ]


def _complete(ctx: JobContext, asset: dict) -> None:
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={"asset_id": asset["id"]},
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"素材已生成 {asset['id']}",
            stage="media",
            progress=0.9,
        )


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    existing, key = job_asset_persistence_attempt(
        ctx.database,
        ctx.job["id"],
    )
    if existing is not None:
        _complete(ctx, existing)
        return

    capability = str(payload.get("capability") or "image")
    prompt = str(payload.get("prompt") or "")
    params = dict(payload.get("parameters") or {})
    input_version_ids = _ids(payload, "input_version_ids")
    input_asset_ids = _ids(payload, "input_asset_ids")
    with UnitOfWork(ctx.database) as uow:
        provider = _provider(uow, capability)
        job = uow.jobs.get(ctx.job["id"])
        project_id = job["project_id"]
        unit_id = job["unit_id"]

    media_provider = build_media_provider(provider, capability)
    task_id = media_provider.submit(prompt, params)
    status, progress = media_provider.poll(task_id)
    while status not in ("done", "failed"):
        if ctx.should_cancel():
            raise JobCanceled()
        ctx.emit(
            f"{capability} 生成中 {int((progress or 0) * 100)}%",
            stage=capability,
            progress=progress,
        )
        ctx.set_progress(progress or 0)
        time.sleep(2)
        status, progress = media_provider.poll(task_id)
    if status == "failed":
        raise RuntimeError(f"{capability} provider 返回失败")

    data = media_provider.fetch(task_id)
    if ctx.should_cancel():
        raise JobCanceled()
    mime_type, suffix = _asset_kind(capability)
    asset = CommandBus(ctx.database).execute(
        PersistGeneratedAssetCommand(
            project_id=project_id,
            unit_id=unit_id,
            data=data,
            filename=f"generated{suffix}",
            media_store=ctx.media_store,
            kind=capability,
            name=payload.get("name") or f"AI {capability}",
            mime_type=mime_type,
            generation={
                "source": "provider",
                "provider": provider["id"],
                "prompt": prompt,
                "parameters": params,
                "task_id": task_id,
                "job_id": ctx.job["id"],
                "input_version_ids": input_version_ids,
                "input_asset_ids": input_asset_ids,
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=ctx.job["id"],
            request_id=str(payload.get("_request_id") or ""),
            turn_id=str(job.get("turn_id") or ""),
            idempotency_key=key,
        ),
    ).result
    _complete(ctx, asset)
