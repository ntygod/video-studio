from __future__ import annotations

import time
import uuid
from typing import Any

from app.domain import TimelineIR


def _pick_edit_plan(artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按状态择优：approved > locked > 最新 draft（修 D5/T4.1）。"""
    candidates = [
        artifact
        for artifact in artifacts
        if artifact["kind"] == "edit_plan" and artifact.get("current_version")
    ]
    if not candidates:
        return None
    rank = {"approved": 0, "locked": 1, "draft": 2}

    def key(artifact):
        status = (artifact["current_version"] or {}).get("status", "")
        return (rank.get(status, 3), -(artifact.get("updated_at") or 0))

    best = min(candidates, key=key)
    return best["current_version"]["payload"]


def _clip_duration(asset: dict[str, Any], decision: dict[str, Any], default: float) -> float:
    """clip 时长优先 AI 决策值，其次 ffprobe 探测值，最后默认值（T4.1）。"""
    requested = float(decision.get("duration") or 0)
    if requested > 0:
        return requested
    probed = float((asset.get("metadata") or {}).get("duration") or 0)
    return probed if probed > 0 else default


def compile_timeline(
    uow,
    project_id: str,
    unit_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    visual_start_by_unit: dict[str, float] = {}
    decisions = (_pick_edit_plan(artifacts) or {}).get("decisions") or []

    def append_visual(asset: dict[str, Any], index: int, duration: float, source_in: float, hold: float, speed: float, volume_db: float, reason: str) -> None:
        nonlocal cursor
        kind = "video" if asset["kind"] == "video" else "image"
        clip = {
            "id": f"clip-{uuid.uuid4().hex[:12]}",
            "asset_id": asset["id"],
            "range": {"start": round(cursor, 3), "duration": round(duration + hold, 3)},
            "source_in": source_in,
            "speed": speed,
            "volume_db": volume_db,
            "metadata": {
                "reason": reason,
                "unit_id": asset.get("unit_id"),
                "shot_index": index,
            },
        }
        tracks[kind].append(clip)
        if asset.get("unit_id") and asset["unit_id"] not in visual_start_by_unit:
            visual_start_by_unit[asset["unit_id"]] = clip["range"]["start"]
        cursor += duration + hold

    for index, decision in enumerate(decisions):
        asset = asset_map.get(decision.get("asset_id") or "")
        if not asset:
            continue
        kind = asset["kind"]
        if kind not in ("video", "image"):
            continue
        duration = _clip_duration(asset, decision, 1.0)
        source_in = float(decision.get("source_in") or 0.0)
        hold = float(decision.get("hold_after") or 0.0)
        speed = float(decision.get("speed") or 1.0)
        volume_db = float((decision.get("audio") or {}).get("duck_db") or 0.0)
        append_visual(
            asset,
            index,
            duration,
            source_in,
            hold,
            speed,
            volume_db,
            decision.get("reason", ""),
        )

    if not decisions:
        for index, asset in enumerate(assets):
            if asset["kind"] not in ("video", "image"):
                continue
            duration = _clip_duration(asset, {}, float(params.get("default_clip_seconds") or 3.0))
            append_visual(asset, index, duration, 0.0, 0.0, 1.0, 0.0, "")

    # 配音：优先对齐到同单元的视频片段起点，否则按顺序排布（修 D5）
    voice_cursor = cursor
    # 没探测到时长时用一个固定兜底值。回退成整条时间线长度会让所有未探测的
    # 配音铺满全片并互相重叠——那正是 D5 的老毛病。
    default_voice = float(params.get("default_voice_seconds") or 3.0)
    voice_assets = [asset for asset in assets if asset["kind"] == "voice"]
    for index, asset in enumerate(voice_assets):
        metadata = asset.get("metadata") or {}
        duration = float(metadata.get("duration") or 0) or default_voice
        start = visual_start_by_unit.get(asset.get("unit_id"))
        if start is None:
            start = voice_cursor
            voice_cursor += duration
        tracks["voice"].append(
            {
                "id": f"voice-{uuid.uuid4().hex[:12]}",
                "asset_id": asset["id"],
                "range": {"start": round(start, 3), "duration": round(duration, 3)},
                "source_in": 0.0,
                "speed": 1.0,
                "volume_db": 0.0,
                "metadata": {
                    "asset": asset["id"],
                    "unit_id": asset.get("unit_id"),
                    "shot_index": index,
                },
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
