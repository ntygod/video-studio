from __future__ import annotations

from typing import Any

from app.integrations.tts.edge import synthesize_edge
from app.store import UnitOfWork


def synthesize_lines(
    settings,
    database,
    project_id: str,
    unit_id: str | None,
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    with UnitOfWork(database) as uow:
        project = uow.projects.get(project_id)
        characters = {item["name"]: item for item in project.bible.characters}
        default_voice = "zh-CN-XiaoxiaoNeural"
    for index, line in enumerate(lines):
        speaker = str(line.get("speaker") or line.get("speaker_id") or "")
        character = characters.get(speaker, {})
        voice = (character.get("voice") or {}).get("voice") or default_voice
        rate = (character.get("voice") or {}).get("speaking_rate")
        rate_text = f"+{int((rate - 1) * 100)}%" if rate and rate != 1 else "+0%"
        uri = synthesize_edge(
            settings,
            project_id,
            str(line.get("text") or ""),
            str(voice),
            rate_text,
            "+0Hz",
            ".mp3",
            unit_id,
        )
        with UnitOfWork(database) as uow:
            asset = uow.assets.create(
                {
                    "project_id": project_id,
                    "unit_id": unit_id,
                    "kind": "voice",
                    "name": f"{speaker or '旁白'}-{index + 1}",
                    "uri": uri,
                    "mime_type": "audio/mpeg",
                    "sha256": "",
                    "generation": {
                        "provider": "edge-tts",
                        "voice": voice,
                        "rate": rate_text,
                        "speaker": speaker,
                    },
                    "metadata": line,
                }
            )
            results.append(asset)
    return results
