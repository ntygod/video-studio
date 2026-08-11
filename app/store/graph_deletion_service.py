"""Block surviving Artifacts before their upstream Artifacts are deleted."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from sqlalchemy import select

from .dependency_models import ArtifactDependencyRow
from .models import ArtifactVersionRow
from .semantic_graph_repository import (
    SemanticArtifactGraphRepository,
)


def block_artifact_deletions(
    session,
    artifact_ids: Iterable[str],
    *,
    excluding_artifact_ids: set[str] | None = None,
) -> list[dict]:
    """Propagate ``blocked`` while dependency edges still exist.

    Artifact and version rows cascade away with a Unit subtree. This function
    runs before that cascade, records the exact deleted upstream version IDs in
    Freshness, and recursively blocks only downstream Artifacts that survive.
    """

    deleted = {str(item) for item in artifact_ids if str(item)}
    excluded = set(excluding_artifact_ids or set())
    if not deleted:
        return []
    graph = SemanticArtifactGraphRepository(session)
    version_rows = session.scalars(
        select(ArtifactVersionRow).where(
            ArtifactVersionRow.artifact_id.in_(deleted)
        )
    ).all()
    deleted_version_ids = {row.id for row in version_rows}
    if not deleted_version_ids:
        return []

    edges = session.scalars(
        select(ArtifactDependencyRow).where(
            ArtifactDependencyRow.upstream_version_id.in_(
                deleted_version_ids
            )
        )
    ).all()
    blocked_by_artifact: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        downstream_id = edge.downstream_artifact_id
        if downstream_id in excluded:
            continue
        downstream = graph._artifact(downstream_id)
        if downstream.current_version_id != edge.downstream_version_id:
            continue
        blocked_by_artifact[downstream_id].add(
            edge.upstream_version_id
        )

    queue: deque[str] = deque(blocked_by_artifact)
    while queue:
        current_id = queue.popleft()
        missing_versions = blocked_by_artifact[current_id]
        current = graph._artifact(current_id)
        graph._set_freshness(
            current,
            "blocked",
            reason=(
                "required upstream Artifact versions were deleted: "
                + ", ".join(sorted(missing_versions))
            ),
            stale_from_version_ids=sorted(missing_versions),
        )
        current_version_ids = select(ArtifactVersionRow.id).where(
            ArtifactVersionRow.artifact_id == current_id
        )
        downstream_edges = session.scalars(
            select(ArtifactDependencyRow).where(
                ArtifactDependencyRow.upstream_version_id.in_(
                    current_version_ids
                )
            )
        ).all()
        for edge in downstream_edges:
            downstream_id = edge.downstream_artifact_id
            if downstream_id in excluded:
                continue
            downstream = graph._artifact(downstream_id)
            if downstream.current_version_id != edge.downstream_version_id:
                continue
            previous = blocked_by_artifact[downstream_id]
            combined = previous | missing_versions
            if combined == previous:
                continue
            blocked_by_artifact[downstream_id] = combined
            queue.append(downstream_id)

    return [
        {
            "artifact_id": artifact_id,
            "blocked_by_version_ids": sorted(version_ids),
            "freshness": graph.get_freshness(artifact_id),
        }
        for artifact_id, version_ids
        in sorted(blocked_by_artifact.items())
    ]


__all__ = ["block_artifact_deletions"]
