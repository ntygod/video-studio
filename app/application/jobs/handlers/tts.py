"""TTS job handler：edge-tts 合成单条配音。"""

from pathlib import Path

from app.integrations.tts.edge import synthesize_edge
from app.store import UnitOfWork

from ..context import JobContext


def _relative_uri(settings, absolute_path: str) -> str:
    return Path(absolute_path).resolve().relative_to(settings.media_dir.resolve()).as_posix()


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    text = str(payload.get("text") or "")
    voice = str(payload.get("voice") or "zh-CN-XiaoxiaoNeural")
    rate = str(payload.get("rate") or "+0%")
    pitch = str(payload.get("pitch") or "+0Hz")
    with UnitOfWork(ctx.database) as uow:
        job = uow.jobs.get(ctx.job["id"])
        unit_id = job["unit_id"]
        project_id = job["project_id"]
    absolute = synthesize_edge(ctx.settings, project_id, text, voice, rate, pitch, ".mp3", unit_id)
    uri = _relative_uri(ctx.settings, absolute)
    metadata: dict = {}
    thumb_uri = ""
    try:
        metadata = ctx.media_store.probe(uri)
        thumb_uri = ctx.media_store.make_thumb(uri, "audio/mpeg")
    except Exception as exc:
        ctx.emit(f"音频探测/波形失败：{exc}", level="warn", stage="tts")
    if ctx.should_cancel():
        raise JobCanceled()
    with UnitOfWork(ctx.database) as uow:
        asset = uow.assets.create(
            {
                "project_id": project_id,
                "unit_id": unit_id,
                "kind": "voice",
                "name": payload.get("name") or "配音",
                "uri": uri,
                "thumb_uri": thumb_uri,
                "mime_type": "audio/mpeg",
                "sha256": "",
                "generation": {"provider": "edge-tts", "voice": voice, "rate": rate},
                "metadata": metadata,
            }
        )
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.9,
            result={"asset_id": asset["id"]},
        )
        uow.jobs.add_event(ctx.job["id"], f"配音已生成 {asset['id']}", stage="tts", progress=0.9)
