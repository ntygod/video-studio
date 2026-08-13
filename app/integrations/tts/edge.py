import asyncio
import hashlib
import json
import uuid
from pathlib import Path

import edge_tts


def edge_output_path(
    settings,
    project_id: str,
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    suffix: str = ".mp3",
    unit_id: str | None = None,
) -> Path:
    """Return a stable content-addressed output path across processes."""

    folder = settings.media_dir / project_id
    if unit_id:
        folder = folder / unit_id
    encoded = json.dumps(
        {
            "project_id": project_id,
            "unit_id": unit_id,
            "text": text,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "suffix": suffix,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:32]
    return folder / f"voice-{digest}{suffix}"


def valid_edge_output(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def synthesize_edge(
    settings,
    project_id: str,
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    suffix: str = ".mp3",
    unit_id: str | None = None,
) -> str:
    target = edge_output_path(
        settings,
        project_id,
        text,
        voice,
        rate,
        pitch,
        suffix,
        unit_id,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if valid_edge_output(target):
        return target.as_posix()
    if target.exists():
        target.unlink(missing_ok=True)

    temporary = target.with_name(
        f".{target.name}.{uuid.uuid4().hex}.part"
    )

    async def _run() -> None:
        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        await communicate.save(str(temporary))

    try:
        asyncio.run(_run())
        if not valid_edge_output(temporary):
            raise RuntimeError("Edge TTS returned an empty audio file")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.as_posix()


__all__ = [
    "edge_output_path",
    "synthesize_edge",
    "valid_edge_output",
]
