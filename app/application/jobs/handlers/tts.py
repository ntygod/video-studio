"""TTS Job handler with recoverable generated-file persistence."""

from pathlib import Path

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedFileAssetCommand,
    job_asset_persistence_attempt,
)
from app.integrations.tts.edge import synthesize_edge
from app.store import UnitOfWork

from ..context import JobContext


def _relative_uri(settings, absolute_path: str) -> str:
    return Path(absolute_path).resolve().relative_to(
        settings.media_dir.resolve()
    ).as_posix()


def _ids(payload: dict, key: str) -> list[str]:
    return [
        value
        for item in payload.get(key) or []
        if (value := str(item or ""))
    ]


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
        asset = existing
    else:
        text = str(payload.get("text") or "")
        voice = str(
            payload.get("voice") or "zh-CN-XiaoxiaoNeural"
        )
        rate = str(payload.get("rate") or "+0%")
        pitch = str(payload.get("pitch") or "+0Hz")
        input_version_ids = _ids(payload, "input_version_ids")
        input_asset_ids = _ids(payload, "input_asset_ids")
        with UnitOfWork(ctx.database) as uow:
            job = uow.jobs.get(ctx.job["id"])
            unit_id = job["unit_id"]
            project_id = job["project_id"]
        absolute = synthesize_edge(
            ctx.settings,
            project_id,
            text,
            voice,
            rate,
            pitch,
            ".mp3",
            unit_id,
        )
        source_uri = _relative_uri(ctx.settings, absolute)
        if ctx.should_cancel():
            ctx.media_store.delete_asset(source_uri)
            raise JobCanceled()
        asset = CommandBus(ctx.database).execute(
            PersistGeneratedFileAssetCommand(
                project_id=project_id,
                unit_id=unit_id,
                source_uri=source_uri,
                media_store=ctx.media_store,
                kind="voice",
                name=payload.get("name") or "配音",
                mime_type="audio/mpeg",
                generation={
                    "provider": "edge-tts",
                    "voice": voice,
                    "rate": rate,
                    "pitch": pitch,
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
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={"asset_id": asset["id"]},
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"配音已生成 {asset['id']}",
            stage="tts",
            progress=0.9,
        )
