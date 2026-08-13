"""TTS Job handler with durable request and generated-file persistence."""

from pathlib import Path

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedFileAssetCommand,
    job_asset_persistence_attempt,
)
from app.application.jobs.runtime_tts_request import (
    prepare_runtime_tts_request,
    reconcile_existing_tts_asset,
)
from app.integrations.tts.edge import (
    edge_output_path,
    synthesize_edge,
    valid_edge_output,
)
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


def _asset_bytes(settings, asset: dict) -> int:
    try:
        return int(
            (settings.media_dir / str(asset.get("uri") or "")).stat().st_size
        )
    except OSError:
        return 0


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
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
        runtime_generation = int(job.get("runtime_generation") or 1)

    existing, key = job_asset_persistence_attempt(
        ctx.database,
        ctx.job["id"],
    )
    if existing is not None:
        asset = existing
        reconcile_existing_tts_asset(
            ctx.database,
            asset,
            request_slot="default",
            text=text,
            audio_bytes=_asset_bytes(ctx.settings, asset),
        )
    else:
        target = edge_output_path(
            ctx.settings,
            project_id,
            text,
            voice,
            rate,
            pitch,
            ".mp3",
            unit_id,
        )
        request = None
        if valid_edge_output(target):
            absolute = target.as_posix()
        else:
            request = prepare_runtime_tts_request(
                ctx.database,
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                job_id=ctx.job["id"],
                runtime_generation=runtime_generation,
                request_slot="default",
            )
            if request is not None:
                request.start()
            try:
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
                if request is not None:
                    request.response_started()
            except JobCanceled:
                raise
            except Exception as exc:
                if request is not None:
                    request.fail(exc)
                raise

        source_uri = _relative_uri(ctx.settings, absolute)
        if ctx.should_cancel():
            # Keep the content-addressed completed response. A later explicit
            # retry can reuse it without making a second external TTS call.
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
        audio_bytes = Path(absolute).stat().st_size
        if request is not None:
            request.complete(
                asset,
                text=text,
                audio_bytes=audio_bytes,
            )
        else:
            reconcile_existing_tts_asset(
                ctx.database,
                asset,
                request_slot="default",
                text=text,
                audio_bytes=audio_bytes,
            )
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
