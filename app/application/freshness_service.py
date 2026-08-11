"""Read models for project-level Artifact freshness surfaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.store.dependency_models import ArtifactFreshnessRow
from app.store.json_codec import loads
from app.store.models import ArtifactRow

FRESHNESS_STATUSES = (
    "fresh",
    "stale",
    "blocked",
    "needs_review",
)
FRESHNESS_PRIORITY = {
    "blocked": 0,
    "stale": 1,
    "needs_review": 2,
    "fresh": 3,
}


def _freshness_item(
    artifact: ArtifactRow,
    row: ArtifactFreshnessRow | None,
    blocked_by_asset_ids: list[str],
) -> dict[str, Any]:
    if row is None:
        status = "fresh"
        reason = ""
        stale_from_version_ids: list[str] = []
        detected_at = None
        updated_at = artifact.updated_at
    else:
        status = row.status
        reason = row.reason
        stale_from_version_ids = loads(
            row.stale_from_version_ids_json,
            [],
        )
        detected_at = row.detected_at
        updated_at = row.updated_at

    return {
        "artifact_id": artifact.id,
        "project_id": artifact.project_id,
        "unit_id": artifact.unit_id,
        "kind": artifact.kind,
        "name": artifact.name,
        "current_version_id": artifact.current_version_id,
        "status": status,
        "reason": reason,
        "stale_from_version_ids": stale_from_version_ids,
        "blocked_by_asset_ids": blocked_by_asset_ids,
        "detected_at": detected_at,
        "updated_at": updated_at,
    }


def list_project_artifact_freshness(
    uow,
    project_id: str,
    *,
    include_fresh: bool = False,
) -> dict[str, Any]:
    """Return counts plus ordered Artifact freshness rows for one project."""

    uow.projects.get(project_id)
    artifacts = uow.session.scalars(
        select(ArtifactRow)
        .where(ArtifactRow.project_id == project_id)
        .order_by(
            ArtifactRow.updated_at.desc(),
            ArtifactRow.id,
        )
    ).all()
    freshness_rows = uow.session.scalars(
        select(ArtifactFreshnessRow).where(
            ArtifactFreshnessRow.project_id == project_id
        )
    ).all()
    by_artifact = {
        row.artifact_id: row for row in freshness_rows
    }

    counts = {status: 0 for status in FRESHNESS_STATUSES}
    items: list[dict[str, Any]] = []
    for artifact in artifacts:
        row = by_artifact.get(artifact.id)
        blocked_by_asset_ids = (
            uow.artifact_graph.blocking_asset_ids(artifact.id)
            if row is not None and row.status == "blocked"
            else []
        )
        item = _freshness_item(
            artifact,
            row,
            blocked_by_asset_ids,
        )
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
        if include_fresh or status != "fresh":
            items.append(item)

    items.sort(
        key=lambda item: (
            FRESHNESS_PRIORITY.get(str(item["status"]), 4),
            -float(item.get("updated_at") or 0.0),
            str(item["artifact_id"]),
        )
    )
    return {"counts": counts, "items": items}


__all__ = [
    "FRESHNESS_PRIORITY",
    "FRESHNESS_STATUSES",
    "list_project_artifact_freshness",
]
