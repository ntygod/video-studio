import asyncio
from pathlib import Path

import edge_tts


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
    folder = settings.media_dir / project_id
    if unit_id:
        folder = folder / unit_id
    folder.mkdir(parents=True, exist_ok=True)
    name = f"voice-{abs(hash((project_id, unit_id, text, voice, rate))):016x}{suffix}"
    target = folder / name
    if target.exists():
        return target.as_posix()

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(target))

    asyncio.run(_run())
    return target.as_posix()
