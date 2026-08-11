from __future__ import annotations

import uuid
from typing import Any

from app.domain import TimelineIR


def pick_edit_plan_artifact(
    artifacts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the exact edit plan selected by compilation."""

    candidates = [
        artifact
        for artifact in artifacts
        if artifact["kind"] == "edit_plan"
        and artifact.get("current_version")
    ]
    if not candidates:
        return None
    rank = {"approved": 0, "locked": 1, "draft": 2}

    def key(artifact):
        status = (
            artifact["current_version"] or {}
        ).get("status", "")
        return (
            rank.get(status, 3),
            -(artifact.get("updated_at") or 0),
        )

    return min(candidates, key=key)


def _clip_duration(
    asset: dict[str, Any],
    decision: dict[str, Any],
    default: float,
) -> float:
    requested = float(decision.get("duration") or 0)
    if requested > 0:
        return requested
    probed = float(
        (asset.get("metadata") or {}).get("duration") or 0
    )
    return probed if probed > 0 else default


def compile_timeline(
    uow,
    project_id: str,
    unit_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    *,
    selected_edit_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = parameters or {}
    width = int(params.get("width", 1080))
    height = int(params.get("height", 1920))
    fps = int(params.get("fps", 30))
    raw_replacements = params.get("asset_replacements") or {}
    replacements = (
        {
            str(source): str(target)
            for source, target in raw_replacements.items()
            if str(source) and str(target)
        }
        if isinstance(raw_replacements, dict)
        else {}
    )
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
    edit_plan = (
        selected_edit_plan
        if selected_edit_plan is not None
        else pick_edit_plan_artifact(artifacts)
    )
    decisions = (
        (
            (edit_plan.get("current_version") or {}).get(
                "payload"
            )
            or {}
        ).get("decisions")
        or []
        if edit_plan
        else []
    )

    def append_visual(
        asset: dict[str, Any],
        index: int,
        duration: float,
        source_in: float,
        hold: float,
        speed: float,
        volume_db: float,
        reason: str,
        replaced_asset_id: str | None = None,
    ) -> None:
        nonlocal cursor
        kind = "video" if asset["kind"] == "video" else "image"
        metadata = {
            "reason": reason,
            "unit_id": asset.get("unit_id"),
            "shot_index": index,
        }
        if replaced_asset_id:
            metadata["replaces_asset_id"] = replaced_asset_id
        clip = {
            "id": f"clip-{uuid.uuid4().hex[:12]}",
            "asset_id": asset["id"],
            "range": {
                "start": round(cursor, 3),
                "duration": round(duration + hold, 3),
            },
            "source_in": source_in,
            "speed": speed,
            "volume_db": volume_db,
            "metadata": metadata,
        }
        tracks[kind].append(clip)
        if (
            asset.get("unit_id")
            and asset["unit_id"] not in visual_start_by_unit
        ):
            visual_start_by_unit[asset["unit_id"]] = clip[
                "range"
            ]["start"]
        cursor += duration + hold

    for index, decision in enumerate(decisions):
        source_asset_id = str(decision.get("asset_id") or "")
        resolved_asset_id = replacements.get(
            source_asset_id,
            source_asset_id,
        )
        asset = asset_map.get(resolved_asset_id)
        if not asset or asset["kind"] not in ("video", "image"):
            continue
        duration = _clip_duration(asset, decision, 1.0)
        append_visual(
            asset,
            index,
            duration,
            float(decision.get("source_in") or 0.0),
            float(decision.get("hold_after") or 0.0),
            float(decision.get("speed") or 1.0),
            float(
                (decision.get("audio") or {}).get("duck_db")
                or 0.0
            ),
            decision.get("reason", ""),
            (
                source_asset_id
                if source_asset_id != resolved_asset_id
                else None
            ),
        )

    if not decisions:
        for index, asset in enumerate(assets):
            if asset["kind"] not in ("video", "image"):
                continue
            duration = _clip_duration(
                asset,
                {},
                float(params.get("default_clip_seconds") or 3.0),
            )
            append_visual(
                asset,
                index,
                duration,
                0.0,
                0.0,
                1.0,
                0.0,
                "",
            )

    voice_cursor = cursor
    default_voice = float(
        params.get("default_voice_seconds") or 3.0
    )
    voice_assets = [
        asset for asset in assets if asset["kind"] == "voice"
    ]
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
                "range": {
                    "start": round(start, 3),
                    "duration": round(duration, 3),
                },
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
            {
                "id": kind + "-track",
                "kind": kind,
                "name": kind,
                "clips": clips,
            }
            for kind, clips in tracks.items()
            if clips
        ],
        duration=max(cursor, 1.0),
    )
    return timeline.model_dump(mode="json")
