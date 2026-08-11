"""Creative Unit repository with subtree-aware dependency invalidation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from .graph_deletion_service import block_artifact_deletions
from .models import ArtifactRow, AssetRow, CreativeUnitRow
from .repositories import NotFoundError, UnitRepository
from .semantic_graph_repository import (
    SemanticArtifactGraphRepository,
)


class SemanticUnitRepository(UnitRepository):
    """Invalidate external dependents before a Unit subtree cascades away."""

    def _subtree_ids(self, root: CreativeUnitRow) -> set[str]:
        rows = self.session.scalars(
            select(CreativeUnitRow).where(
                CreativeUnitRow.project_id == root.project_id
            )
        ).all()
        children: dict[str | None, list[str]] = defaultdict(list)
        for row in rows:
            children[row.parent_id].append(row.id)
        result: set[str] = set()
        frontier = [root.id]
        while frontier:
            unit_id = frontier.pop()
            if unit_id in result:
                continue
            result.add(unit_id)
            frontier.extend(children.get(unit_id, []))
        return result

    def delete(self, unit_id: str) -> list[dict[str, Any]]:
        row = self.session.get(CreativeUnitRow, unit_id)
        if row is None:
            raise NotFoundError(unit_id)
        unit_ids = self._subtree_ids(row)
        asset_ids = list(
            self.session.scalars(
                select(AssetRow.id).where(
                    AssetRow.unit_id.in_(unit_ids)
                )
            ).all()
        )
        deleted_artifact_ids = set(
            self.session.scalars(
                select(ArtifactRow.id).where(
                    ArtifactRow.unit_id.in_(unit_ids)
                )
            ).all()
        )
        asset_impacts = SemanticArtifactGraphRepository(
            self.session
        ).on_assets_deleted(
            asset_ids,
            excluding_artifact_ids=deleted_artifact_ids,
        )
        artifact_impacts = block_artifact_deletions(
            self.session,
            deleted_artifact_ids,
            excluding_artifact_ids=deleted_artifact_ids,
        )
        self.session.delete(row)
        self.session.flush()
        by_artifact: dict[str, dict[str, Any]] = {}
        for impact in [*asset_impacts, *artifact_impacts]:
            by_artifact[impact["artifact_id"]] = impact
        return list(by_artifact.values())


__all__ = ["SemanticUnitRepository"]
