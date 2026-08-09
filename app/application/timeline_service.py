from __future__ import annotations

import time
import uuid
from typing import Any

from app.domain import TimelineIR


def compile_timeline(uow, project_id: str, unit_id: str | None = None, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = parameters or {}
    width = int(params.get("width", 1080))
    height = int(params.get("height", 1920))
    fps = int(params.get("fps", 30))
    artifacts = uow.artifacts.list(project_id, unit_id=unit_id)
    assets = uow.assets.list(project_id, unit_id=unit_id)
    asset_map = {asset["id"]: asset for asset in assets}
    tracks: dict[str, list[dict[str, Any]]] = {
        "video": [],
        "image": [],
        "voice": [],
        "music": [],
        "sfx": [],
        "subtitle": [],
    }
    cursor = 0.0
    edit_plan = None
    for artifact in artifacts:
        if artifact["kind"] == "edit_plan" and artifact.get("current_version"):
            edit_plan = artifact["current_version"]["payload"]
    decisions = (edit_plan or {}).get("decisions") or []
    for index, decision in enumerate(decisions):
        asset = asset_map.get(decision.get("asset_id") or "")
        if not asset:
            continue
        kind = asset["kind"]
        if kind not in tracks:
            continue
        duration = float(decision.get("duration") or 1.0)
        source_in = float(decision.get("source_in") or 0.0)
        hold = float(decision.get("hold_after") or 0.0)
        track_kind = "video" if kind == "video" else "image" if kind == "image" else kind
        tracks[track_kind].append(
            {
                "id": f"clip-{uuid.uuid4().hex[:12]}",
                "asset_id": asset["uri"],
                "range": {"start": round(cursor, 3), "duration": round(duration + hold, 3)},
                "source_in": source_in,
                "speed": float(decision.get("speed") or 1.0),
                "volume_db": float((decision.get("audio") or {}).get("duck_db") or 0.0),
                "metadata": {"reason": decision.get("reason", "")},
            }
        )
        cursor += duration + hold
    if not decisions:
        for asset in assets:
            if asset["kind"] not in ("video", "image"):
                continue
            kind = "video" if asset["kind"] == "video" else "image"
            duration = float((params.get("default_clip_seconds") or 3.0))
            tracks[kind].append(
                {
                    "id": f"clip-{uuid.uuid4().hex[:12]}",
                    "asset_id": asset["uri"],
                    "range": {"start": round(cursor, 3), "duration": duration},
                    "source_in": 0.0,
                    "speed": 1.0,
                    "volume_db": 0.0,
                    "metadata": {},
                }
            )
            cursor += duration
    voice_assets = [asset for asset in assets if asset["kind"] == "voice"]
    for index, asset in enumerate(voice_assets):
        tracks["voice"].append(
            {
                "id": f"voice-{uuid.uuid4().hex[:12]}",
                "asset_id": asset["uri"],
                "range": {"start": 0.0, "duration": max(cursor, 1.0)},
                "source_in": 0.0,
                "speed": 1.0,
                "volume_db": 0.0,
                "metadata": {"asset": asset["id"]},
            }
        )
    timeline = TimelineIR(
        width=width,
        height=height,
        fps=fps,
        tracks=[
            {"id": kind + "-track", "kind": kind, "name": kind, "clips": clips}
            for kind, clips in tracks.items()
            if clips
        ],
        duration=max(cursor, 1.0),
    )
    return timeline.model_dump(mode="json")
