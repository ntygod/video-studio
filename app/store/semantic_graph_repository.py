"""Safe Artifact graph with first-class immutable Asset inputs."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy import func, select

from .dependency_models import (
    ArtifactDependencyRow,
    ArtifactProvenanceRow,
    AssetDependencyRow,
)
from .dependency_repository import ArtifactGraphRepository
from .json_codec import dumps, loads
from .models import ArtifactRow, ArtifactVersionRow, AssetRow
from .repositories import ConflictError, NotFoundError, new_id

MAX_DERIVATION_INPUTS = 500
MAX_PROJECT_ARTIFACT_DEPENDENCIES = 50_000
MAX_PROJECT_ASSET_DEPENDENCIES = 100_000


class SemanticArtifactGraphRepository(ArtifactGraphRepository):
    """Enforce graph safety and retain deleted Asset dependencies."""

    @staticmethod
    def _asset_snapshot(row: AssetRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "shot_id": row.shot_id,
            "kind": row.kind,
            "name": row.name,
            "uri": row.uri,
            "thumb_uri": row.thumb_uri,
            "mime_type": row.mime_type,
            "sha256": row.sha256,
            "parent_asset_id": row.parent_asset_id,
            "created_at": row.created_at,
        }

    def _asset_dependency(
        self,
        row: AssetDependencyRow,
    ) -> dict[str, Any]:
        asset = self.session.get(AssetRow, row.upstream_asset_id)
        return {
            "id": row.id,
            "project_id": row.project_id,
            "upstream_asset_id": row.upstream_asset_id,
            "upstream_asset": (
                self._asset_snapshot(asset)
                if asset is not None
                else loads(row.upstream_asset_snapshot_json, {})
            ),
            "asset_exists": asset is not None,
            "downstream_artifact_id": row.downstream_artifact_id,
            "downstream_version_id": row.downstream_version_id,
            "dependency_type": row.dependency_type,
            "metadata": loads(row.metadata_json, {}),
            "created_at": row.created_at,
        }

    def _artifact_adjacency(
        self,
        project_id: str,
    ) -> dict[str, set[str]]:
        rows = self.session.execute(
            select(
                ArtifactVersionRow.artifact_id,
                ArtifactDependencyRow.downstream_artifact_id,
            )
            .join(
                ArtifactDependencyRow,
                ArtifactDependencyRow.upstream_version_id
                == ArtifactVersionRow.id,
            )
            .where(
                ArtifactDependencyRow.project_id == project_id
            )
        ).all()
        result: dict[str, set[str]] = defaultdict(set)
        for upstream_id, downstream_id in rows:
            result[str(upstream_id)].add(str(downstream_id))
        return result

    @staticmethod
    def _reachable_from(
        adjacency: dict[str, set[str]],
        start: str,
    ) -> set[str]:
        visited: set[str] = set()
        frontier = [start]
        while frontier:
            current = frontier.pop()
            for downstream in adjacency.get(current, set()):
                if downstream in visited:
                    continue
                visited.add(downstream)
                frontier.append(downstream)
        return visited

    def _assert_artifact_derivation_safe(
        self,
        output: ArtifactVersionRow,
        inputs: list[str],
    ) -> None:
        if len(inputs) > MAX_DERIVATION_INPUTS:
            raise ConflictError(
                f"derivation cannot exceed {MAX_DERIVATION_INPUTS} inputs"
            )
        output_artifact = self._artifact(output.artifact_id)
        input_rows = [self._version(version_id) for version_id in inputs]
        input_artifacts = [
            self._artifact(row.artifact_id) for row in input_rows
        ]
        if any(
            artifact.project_id != output_artifact.project_id
            for artifact in input_artifacts
        ):
            raise ConflictError(
                "artifact dependency cannot cross projects"
            )
        input_artifact_ids = {
            artifact.id for artifact in input_artifacts
        }
        if output_artifact.id in input_artifact_ids:
            raise ConflictError(
                "artifact cannot depend on another version of itself"
            )

        edge_count = int(
            self.session.scalar(
                select(func.count(ArtifactDependencyRow.id)).where(
                    ArtifactDependencyRow.project_id
                    == output_artifact.project_id
                )
            )
            or 0
        )
        if (
            edge_count + len(inputs)
            > MAX_PROJECT_ARTIFACT_DEPENDENCIES
        ):
            raise ConflictError(
                "project Artifact dependency graph exceeds its safety limit"
            )

        reachable = self._reachable_from(
            self._artifact_adjacency(output_artifact.project_id),
            output_artifact.id,
        )
        cycle_inputs = sorted(input_artifact_ids & reachable)
        if cycle_inputs:
            raise ConflictError(
                "artifact dependency would create a cycle: "
                + ", ".join(cycle_inputs)
            )

    def register_derivation(
        self,
        output_version_id: str,
        input_version_ids: list[str],
        *,
        dependency_type: str = "derived_from",
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        inputs = list(
            dict.fromkeys(
                str(item)
                for item in input_version_ids
                if str(item)
            )
        )
        existing_edges = self.session.scalar(
            select(func.count(ArtifactDependencyRow.id)).where(
                ArtifactDependencyRow.downstream_version_id
                == output_version_id
            )
        )
        existing_provenance = self.session.scalar(
            select(ArtifactProvenanceRow.id).where(
                ArtifactProvenanceRow.artifact_version_id
                == output_version_id
            )
        )
        if not existing_edges and not existing_provenance:
            output = self._version(output_version_id)
            self._assert_artifact_derivation_safe(output, inputs)
        return super().register_derivation(
            output_version_id,
            inputs,
            dependency_type=dependency_type,
            metadata=metadata,
            provenance=provenance,
        )

    def register_asset_dependencies(
        self,
        output_version_id: str,
        input_asset_ids: Iterable[str],
        *,
        dependency_type: str = "uses_asset",
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        asset_ids = list(
            dict.fromkeys(
                str(item) for item in input_asset_ids if str(item)
            )
        )
        if len(asset_ids) > MAX_DERIVATION_INPUTS:
            raise ConflictError(
                f"derivation cannot exceed {MAX_DERIVATION_INPUTS} Asset inputs"
            )
        output = self._version(output_version_id)
        output_artifact = self._artifact(output.artifact_id)
        existing = self.session.scalars(
            select(AssetDependencyRow).where(
                AssetDependencyRow.downstream_version_id
                == output_version_id
            )
        ).all()
        if existing:
            existing_ids = sorted(
                row.upstream_asset_id for row in existing
            )
            if existing_ids != sorted(asset_ids):
                raise ConflictError(
                    "artifact version already has different Asset inputs"
                )
            if any(
                row.dependency_type != dependency_type
                or loads(row.metadata_json, {}) != (metadata or {})
                for row in existing
            ):
                raise ConflictError(
                    "artifact version already has different Asset dependency metadata"
                )
            return [self._asset_dependency(row) for row in existing]
        if not asset_ids:
            return []

        assets: list[AssetRow] = []
        for asset_id in asset_ids:
            asset = self.session.get(AssetRow, asset_id)
            if asset is None:
                raise NotFoundError(asset_id)
            if asset.project_id != output_artifact.project_id:
                raise ConflictError(
                    "Asset dependency cannot cross projects"
                )
            assets.append(asset)

        edge_count = int(
            self.session.scalar(
                select(func.count(AssetDependencyRow.id)).where(
                    AssetDependencyRow.project_id
                    == output_artifact.project_id
                )
            )
            or 0
        )
        if edge_count + len(assets) > MAX_PROJECT_ASSET_DEPENDENCIES:
            raise ConflictError(
                "project Asset dependency graph exceeds its safety limit"
            )

        now = time.time()
        rows: list[AssetDependencyRow] = []
        for asset in assets:
            row = AssetDependencyRow(
                id=new_id(),
                project_id=output_artifact.project_id,
                upstream_asset_id=asset.id,
                upstream_asset_snapshot_json=dumps(
                    self._asset_snapshot(asset)
                ),
                downstream_artifact_id=output_artifact.id,
                downstream_version_id=output_version_id,
                dependency_type=str(
                    dependency_type or "uses_asset"
                ),
                metadata_json=dumps(metadata or {}),
                created_at=now,
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return [self._asset_dependency(row) for row in rows]

    def asset_dependencies_for_version(
        self,
        version_id: str,
    ) -> list[dict[str, Any]]:
        self._version(version_id)
        rows = self.session.scalars(
            select(AssetDependencyRow)
            .where(
                AssetDependencyRow.downstream_version_id
                == version_id
            )
            .order_by(AssetDependencyRow.created_at)
        ).all()
        return [self._asset_dependency(row) for row in rows]

    def asset_dependencies_for_artifact(
        self,
        artifact_id: str,
    ) -> list[dict[str, Any]]:
        self._artifact(artifact_id)
        rows = self.session.scalars(
            select(AssetDependencyRow)
            .where(
                AssetDependencyRow.downstream_artifact_id
                == artifact_id
            )
            .order_by(AssetDependencyRow.created_at)
        ).all()
        return [self._asset_dependency(row) for row in rows]

    def dependents_for_asset(
        self,
        asset_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(AssetDependencyRow)
            .where(
                AssetDependencyRow.upstream_asset_id == asset_id
            )
            .order_by(AssetDependencyRow.created_at)
        ).all()
        return [self._asset_dependency(row) for row in rows]

    def _blocking_asset_ids(
        self,
        artifact_id: str,
        visited: set[str],
    ) -> set[str]:
        if artifact_id in visited:
            return set()
        visited.add(artifact_id)
        artifact = self._artifact(artifact_id)
        current_version_id = artifact.current_version_id
        if not current_version_id:
            return set()

        result: set[str] = set()
        asset_rows = self.session.scalars(
            select(AssetDependencyRow).where(
                AssetDependencyRow.downstream_version_id
                == current_version_id
            )
        ).all()
        for row in asset_rows:
            if self.session.get(AssetRow, row.upstream_asset_id) is None:
                result.add(row.upstream_asset_id)

        upstream_rows = self.session.scalars(
            select(ArtifactDependencyRow).where(
                ArtifactDependencyRow.downstream_version_id
                == current_version_id
            )
        ).all()
        for edge in upstream_rows:
            version = self._version(edge.upstream_version_id)
            upstream = self._artifact(version.artifact_id)
            upstream_freshness = super().get_freshness(upstream.id)
            if upstream_freshness["status"] == "blocked":
                result.update(
                    self._blocking_asset_ids(
                        upstream.id,
                        visited,
                    )
                )
        return result

    def blocking_asset_ids(self, artifact_id: str) -> list[str]:
        return sorted(
            self._blocking_asset_ids(artifact_id, set())
        )

    def get_freshness(self, artifact_id: str) -> dict[str, Any]:
        freshness = super().get_freshness(artifact_id)
        freshness["blocked_by_asset_ids"] = (
            self.blocking_asset_ids(artifact_id)
            if freshness["status"] == "blocked"
            else []
        )
        return freshness

    def derivation(self, output_version_id: str) -> dict[str, Any]:
        result = super().derivation(output_version_id)
        result["asset_dependencies"] = (
            self.asset_dependencies_for_version(output_version_id)
        )
        result["freshness"] = self.get_freshness(
            result["artifact_id"]
        )
        return result

    def on_assets_deleted(
        self,
        asset_ids: Iterable[str],
        *,
        excluding_artifact_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        missing = {
            str(item) for item in asset_ids if str(item)
        }
        excluded = set(excluding_artifact_ids or set())
        if not missing:
            return []
        rows = self.session.scalars(
            select(AssetDependencyRow).where(
                AssetDependencyRow.upstream_asset_id.in_(missing)
            )
        ).all()

        blocked_by_artifact: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row.downstream_artifact_id in excluded:
                continue
            downstream = self._artifact(row.downstream_artifact_id)
            if downstream.current_version_id != row.downstream_version_id:
                continue
            blocked_by_artifact[downstream.id].add(
                row.upstream_asset_id
            )

        queue: deque[str] = deque(blocked_by_artifact)
        while queue:
            current_id = queue.popleft()
            current_assets = blocked_by_artifact[current_id]
            current = self._artifact(current_id)
            self._set_freshness(
                current,
                "blocked",
                reason=(
                    "required Asset inputs are missing: "
                    + ", ".join(sorted(current_assets))
                ),
            )
            version_ids = select(ArtifactVersionRow.id).where(
                ArtifactVersionRow.artifact_id == current_id
            )
            edges = self.session.scalars(
                select(ArtifactDependencyRow).where(
                    ArtifactDependencyRow.upstream_version_id.in_(
                        version_ids
                    )
                )
            ).all()
            for edge in edges:
                downstream_id = edge.downstream_artifact_id
                if downstream_id in excluded:
                    continue
                downstream = self._artifact(downstream_id)
                if (
                    downstream.current_version_id
                    != edge.downstream_version_id
                ):
                    continue
                previous = blocked_by_artifact[downstream_id]
                combined = previous | current_assets
                if combined == previous:
                    continue
                blocked_by_artifact[downstream_id] = combined
                queue.append(downstream_id)

        return [
            {
                "artifact_id": artifact_id,
                "blocked_by_asset_ids": sorted(asset_ids_for_artifact),
                "freshness": self.get_freshness(artifact_id),
            }
            for artifact_id, asset_ids_for_artifact
            in sorted(blocked_by_artifact.items())
        ]

    def on_new_version(
        self,
        artifact_id: str,
        new_version_id: str,
    ) -> list[dict[str, Any]]:
        artifact = self._artifact(artifact_id)
        if artifact.current_version_id != new_version_id:
            return []
        self._set_freshness(artifact, "fresh")
        impacted: list[dict[str, Any]] = []
        queue = [artifact_id]
        visited = {artifact_id}
        while queue:
            changed_artifact_id = queue.pop(0)
            version_ids = select(ArtifactVersionRow.id).where(
                ArtifactVersionRow.artifact_id
                == changed_artifact_id
            )
            edges = self.session.scalars(
                select(ArtifactDependencyRow).where(
                    ArtifactDependencyRow.upstream_version_id.in_(
                        version_ids
                    )
                )
            ).all()
            for edge in edges:
                downstream = self._artifact(
                    edge.downstream_artifact_id
                )
                if (
                    downstream.current_version_id
                    != edge.downstream_version_id
                    or downstream.id == artifact_id
                ):
                    continue
                existing = super().get_freshness(downstream.id)
                if existing["status"] == "blocked":
                    freshness = self.get_freshness(downstream.id)
                else:
                    freshness = self._set_freshness(
                        downstream,
                        "stale",
                        reason=(
                            f"upstream artifact {artifact_id} advanced "
                            f"to version {new_version_id}"
                        ),
                        stale_from_version_ids=[new_version_id],
                    )
                if downstream.id not in visited:
                    visited.add(downstream.id)
                    queue.append(downstream.id)
                    impacted.append(
                        {
                            "artifact_id": downstream.id,
                            "via_dependency_id": edge.id,
                            "freshness": freshness,
                        }
                    )
        return impacted


__all__ = [
    "MAX_DERIVATION_INPUTS",
    "MAX_PROJECT_ARTIFACT_DEPENDENCIES",
    "MAX_PROJECT_ASSET_DEPENDENCIES",
    "SemanticArtifactGraphRepository",
]
