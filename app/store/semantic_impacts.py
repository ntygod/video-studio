"""Collect secondary semantic mutations for OperationLog audit."""

from __future__ import annotations

from typing import Any, Iterable

_SESSION_KEY = "video_studio.semantic_affected_entities"


def _entity_key(entity: dict[str, Any]) -> tuple[str, str] | None:
    entity_type = str(entity.get("type") or "")
    entity_id = str(entity.get("id") or "")
    if not entity_type or not entity_id:
        return None
    return entity_type, entity_id


def merge_affected_entities(
    *groups: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge entity references while preserving first-seen order."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for entity in group:
            key = _entity_key(entity)
            if key is None or key in seen:
                continue
            seen.add(key)
            result.append({"type": key[0], "id": key[1]})
    return result


def record_affected_entities(
    session,
    entities: Iterable[dict[str, Any]],
) -> None:
    existing = list(session.info.get(_SESSION_KEY) or [])
    session.info[_SESSION_KEY] = merge_affected_entities(
        existing,
        entities,
    )


def record_artifact_impacts(
    session,
    impacts: Iterable[dict[str, Any]],
) -> None:
    entities: list[dict[str, Any]] = []
    for impact in impacts:
        artifact_id = str(impact.get("artifact_id") or "")
        if not artifact_id:
            continue
        entities.extend(
            [
                {"type": "artifact", "id": artifact_id},
                {
                    "type": "artifact_freshness",
                    "id": artifact_id,
                },
            ]
        )
    record_affected_entities(session, entities)


def take_affected_entities(session) -> list[dict[str, Any]]:
    return list(session.info.pop(_SESSION_KEY, []) or [])


__all__ = [
    "merge_affected_entities",
    "record_affected_entities",
    "record_artifact_impacts",
    "take_affected_entities",
]
