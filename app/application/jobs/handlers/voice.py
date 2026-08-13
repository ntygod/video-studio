"""Batch voice synthesis with durable per-line request and Asset slots."""

from pathlib import Path
from typing import Any

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


def _relative_uri(ctx: JobContext, absolute_path: str) -> str:
    return (
        Path(absolute_path)
        .resolve()
        .relative_to(ctx.settings.media_dir.resolve())
        .as_posix()
    )


def _character_map(project) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in project.bible.characters:
        item = (
            raw.model_dump(mode="json")
            if hasattr(raw, "model_dump")
            else dict(raw)
        )
        result[str(item.get("name") or "")] = item
    return result


def _asset_bytes(ctx: JobContext, asset: dict[str, Any]) -> int:
    try:
        return int(
            (
                ctx.settings.media_dir
                / str(asset.get("uri") or "")
            ).stat().st_size
        )
    except OSError:
        return 0


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
        runtime_generation = int(job.get("runtime_generation") or 1)
        project = uow.projects.get(project_id)
    characters = _character_map(project)
    default_voice = "zh-CN-XiaoxiaoNeural"
    total = max(len(lines), 1)
    assets: list[dict[str, Any]] = []

    for index, line in enumerate(lines):
        if ctx.should_cancel():
            raise JobCanceled()
        slot = f"voice-line-{index}"
        speaker = str(
            line.get("speaker")
            or line.get("speaker_id")
            or ""
        )
        text = str(line.get("text") or "")
        character = characters.get(speaker, {})
        voice_profile = character.get("voice") or {}
        voice = str(
            voice_profile.get("voice") or default_voice
        )
        rate = voice_profile.get("speaking_rate")
        rate_text = (
            f"{int((float(rate) - 1) * 100):+d}%"
            if rate and float(rate) != 1
            else "+0%"
        )
        pitch = "+0Hz"
        existing, key = job_asset_persistence_attempt(
            ctx.database,
            ctx.job["id"],
            slot=slot,
        )
        if existing is not None:
            asset = existing
            reconcile_existing_tts_asset(
                ctx.database,
                asset,
                request_slot=slot,
                text=text,
                audio_bytes=_asset_bytes(ctx, asset),
            )
        else:
            target = edge_output_path(
                ctx.settings,
                project_id,
                text,
                voice,
                rate_text,
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
                    rate=rate_text,
                    pitch=pitch,
                    job_id=ctx.job["id"],
                    runtime_generation=runtime_generation,
                    request_slot=slot,
                )
                if request is not None:
                    request.start()
                try:
                    absolute = synthesize_edge(
                        ctx.settings,
                        project_id,
                        text,
                        voice,
                        rate_text,
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

            source_uri = _relative_uri(ctx, absolute)
            if ctx.should_cancel():
                raise JobCanceled()
            asset = CommandBus(ctx.database).execute(
                PersistGeneratedFileAssetCommand(
                    project_id=project_id,
                    unit_id=unit_id,
                    source_uri=source_uri,
                    media_store=ctx.media_store,
                    kind="voice",
                    name=f"{speaker or '旁白'}-{index + 1}",
                    mime_type="audio/mpeg",
                    generation={
                        "provider": "edge-tts",
                        "voice": voice,
                        "rate": rate_text,
                        "speaker": speaker,
                        "job_id": ctx.job["id"],
                        "slot": slot,
                    },
                    metadata=dict(line),
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
                    request_slot=slot,
                    text=text,
                    audio_bytes=audio_bytes,
                )
        assets.append(asset)
        progress = 0.9 * (index + 1) / total
        ctx.set_progress(progress)
        ctx.emit(
            f"已合成 {index + 1}/{len(lines)} 条声音",
            stage="voice",
            progress=progress,
        )

    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={
                "asset_ids": [asset["id"] for asset in assets],
                "count": len(assets),
            },
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"已合成 {len(assets)} 条声音",
            stage="voice",
            progress=0.9,
        )
