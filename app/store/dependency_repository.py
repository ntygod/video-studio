"""Repository for version-level Artifact graph and freshness propagation."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from .dependency_models import (
    ArtifactDependencyRow,
    ArtifactFreshnessRow,
    ArtifactProvenanceRow,
)
from .json_codec import dumps, loads
from .models import ArtifactRow, ArtifactVersionRow
from .repositories import ConflictError, NotFoundError, new_id

FRESHNESS_STATUSES = frozenset(
    {"fresh", "stale", "blocked", "needs_review"}
)


class ArtifactGraphRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _dependency(row: ArtifactDependencyRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "upstream_version_id": row.upstream_version_id,
            "downstream_artifact_id": row.downstream_artifact_id,
            "downstream_version_id": row.downstream_version_id,
            "dependency_type": row.dependency_type,
            "metadata": loads(row.metadata_json, {}),
            "created_at": row.created_at,
        }

    @staticmethod
    def _provenance(row: ArtifactProvenanceRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "artifact_version_id": row.artifact_version_id,
            "input_version_ids": loads(
                row.input_version_ids_json,
                [],
            ),
            "provider_profile_id": row.provider_profile_id,
            "model_id": row.model_id,
            "prompt_version": row.prompt_version,
            "parameters": loads(row.parameters_json, {}),
            "seed": row.seed,
            "task_attempt_id": row.task_attempt_id,
            "operation_id": row.operation_id,
            "created_at": row.created_at,
        }

    @staticmethod
    def _freshness(row: ArtifactFreshnessRow) -> dict[str, Any]:
        return {
            "artifact_id": row.artifact_id,
            "project_id": row.project_id,
            "status": row.status,
            "reason": row.reason,
            "stale_from_version_ids": loads(
                row.stale_from_version_ids_json,
                [],
            ),
            "detected_at": row.detected_at,
            "updated_at": row.updated_at,
        }

    def _artifact(self, artifact_id: str) -> ArtifactRow:
        row = self.session.get(ArtifactRow, artifact_id)
        if row is None:
            raise NotFoundError(artifact_id)
        return row

    def _version(self, version_id: str) -> ArtifactVersionRow:
        row = self.session.get(ArtifactVersionRow, version_id)
        if row is None:
            raise NotFoundError(version_id)
        return row

    def _set_freshness(
        self,
        artifact: ArtifactRow,
        status: str,
        *,
        reason: str = "",
        stale_from_version_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if status not in FRESHNESS_STATUSES:
            raise ValueError(f"invalid freshness status: {status}")
        now = time.time()
        row = self.session.get(ArtifactFreshnessRow, artifact.id)
        if row is None:
            row = ArtifactFreshnessRow(
                artifact_id=artifact.id,
                project_id=artifact.project_id,
                status=status,
                reason=reason,
                stale_from_version_ids_json=dumps(
                    sorted(set(stale_from_version_ids or []))
                ),
                detected_at=(
                    now if status != "fresh" else None
                ),
                updated_at=now,
            )
            self.session.add(row)
        else:
            existing = set(
                loads(row.stale_from_version_ids_json, [])
            )
            incoming = set(stale_from_version_ids or [])
            row.status = status
            row.reason = reason
            row.stale_from_version_ids_json = dumps(
                sorted(existing | incoming)
                if status != "fresh"
                else []
            )
            row.detected_at = (
                row.detected_at or now
                if status != "fresh"
                else None
            )
            row.updated_at = now
        self.session.flush()
        return self._freshness(row)

    def get_freshness(self, artifact_id: str) -> dict[str, Any]:
        artifact = self._artifact(artifact_id)
        row = self.session.get(ArtifactFreshnessRow, artifact_id)
        if row is None:
            return {
                "artifact_id": artifact.id,
                "project_id": artifact.project_id,
                "status": "fresh",
                "reason": "",
                "stale_from_version_ids": [],
                "detected_at": None,
                "updated_at": artifact.updated_at,
            }
        return self._freshness(row)

    def provenance(self, version_id: str) -> dict[str, Any] | None:
        self._version(version_id)
        row = self.session.scalar(
            select(ArtifactProvenanceRow).where(
                ArtifactProvenanceRow.artifact_version_id
                == version_id
            )
        )
        return self._provenance(row) if row else None

    def dependencies_for_artifact(
        self,
        artifact_id: str,
    ) -> list[dict[str, Any]]:
        self._artifact(artifact_id)
        version_ids = select(ArtifactVersionRow.id).where(
            ArtifactVersionRow.artifact_id == artifact_id
        )
        rows = self.session.scalars(
            select(ArtifactDependencyRow)
            .where(
                (
                    ArtifactDependencyRow.downstream_artifact_id
                    == artifact_id
                )
                | (
                    ArtifactDependencyRow.upstream_version_id.in_(
                        version_ids
                    )
                )
            )
            .order_by(ArtifactDependencyRow.created_at)
        ).all()
        return [self._dependency(row) for row in rows]

    def derivation(self, output_version_id: str) -> dict[str, Any]:
        output = self._version(output_version_id)
        artifact = self._artifact(output.artifact_id)
        rows = self.session.scalars(
            select(ArtifactDependencyRow)
            .where(
                ArtifactDependencyRow.downstream_version_id
                == output_version_id
            )
            .order_by(ArtifactDependencyRow.created_at)
        ).all()
        return {
            "artifact_id": artifact.id,
            "artifact_version_id": output_version_id,
            "dependencies": [
                self._dependency(row) for row in rows
            ],
            "provenance": self.provenance(output_version_id),
            "freshness": self.get_freshness(artifact.id),
        }

    def register_derivation(
        self,
        output_version_id: str,
        input_version_ids: list[str],
        *,
        dependency_type: str = "derived_from",
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        output = self._version(output_version_id)
        output_artifact = self._artifact(output.artifact_id)
        inputs = list(dict.fromkeys(str(item) for item in input_version_ids))
        if not inputs:
            raise ValueError("derivation requires at least one input version")
        if output_version_id in inputs:
            raise ConflictError("artifact version cannot depend on itself")
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

        existing = self.session.scalars(
            select(ArtifactDependencyRow).where(
                ArtifactDependencyRow.downstream_version_id
                == output_version_id
            )
        ).all()
        existing_provenance = self.session.scalar(
            select(ArtifactProvenanceRow).where(
                ArtifactProvenanceRow.artifact_version_id
                == output_version_id
            )
        )
        if existing or existing_provenance:
            existing_inputs = sorted(
                row.upstream_version_id for row in existing
            )
            if existing_inputs != sorted(inputs):
                raise ConflictError(
                    "artifact version already has different inputs"
                )
            return self.derivation(output_version_id)

        now = time.time()
        for input_id in inputs:
            self.session.add(
                ArtifactDependencyRow(
                    id=new_id(),
                    project_id=output_artifact.project_id,
                    upstream_version_id=input_id,
                    downstream_artifact_id=output_artifact.id,
                    downstream_version_id=output_version_id,
                    dependency_type=(
                        str(dependency_type or "derived_from")
                    ),
                    metadata_json=dumps(metadata or {}),
                    created_at=now,
                )
            )
        provenance_data = deepcopy(provenance or {})
        self.session.add(
            ArtifactProvenanceRow(
                id=new_id(),
                project_id=output_artifact.project_id,
                artifact_version_id=output_version_id,
                input_version_ids_json=dumps(inputs),
                provider_profile_id=str(
                    provenance_data.get("provider_profile_id") or ""
                ),
                model_id=str(provenance_data.get("model_id") or ""),
                prompt_version=str(
                    provenance_data.get("prompt_version") or ""
                ),
                parameters_json=dumps(
                    provenance_data.get("parameters") or {}
                ),
                seed=str(provenance_data.get("seed") or ""),
                task_attempt_id=str(
                    provenance_data.get("task_attempt_id") or ""
                ),
                operation_id=str(
                    provenance_data.get("operation_id") or ""
                ),
                created_at=now,
            )
        )
        self.session.flush()

        stale_sources: list[str] = []
        blocked = False
        for version, artifact in zip(
            input_rows,
            input_artifacts,
            strict=True,
        ):
            if artifact.current_version_id != version.id:
                stale_sources.append(version.id)
            input_freshness = self.get_freshness(artifact.id)
            if input_freshness["status"] == "blocked":
                blocked = True
                stale_sources.extend(
                    input_freshness["stale_from_version_ids"]
                )
            elif input_freshness["status"] != "fresh":
                stale_sources.extend(
                    input_freshness["stale_from_version_ids"]
                    or [version.id]
                )
        if output_artifact.current_version_id == output_version_id:
            if blocked:
                self._set_freshness(
                    output_artifact,
                    "blocked",
                    reason="one or more inputs are blocked",
                    stale_from_version_ids=stale_sources,
                )
            elif stale_sources:
                self._set_freshness(
                    output_artifact,
                    "stale",
                    reason="derivation uses non-current or stale inputs",
                    stale_from_version_ids=stale_sources,
                )
            else:
                self._set_freshness(output_artifact, "fresh")
        return self.derivation(output_version_id)

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
                ):
                    continue
                if downstream.id == artifact_id:
                    continue
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

    def impact(self, artifact_id: str) -> list[dict[str, Any]]:
        self._artifact(artifact_id)
        result: list[dict[str, Any]] = []
        queue = [artifact_id]
        visited = {artifact_id}
        while queue:
            current = queue.pop(0)
            version_ids = select(ArtifactVersionRow.id).where(
                ArtifactVersionRow.artifact_id == current
            )
            edges = self.session.scalars(
                select(ArtifactDependencyRow).where(
                    ArtifactDependencyRow.upstream_version_id.in_(
                        version_ids
                    )
                )
            ).all()
            for edge in edges:
                downstream = self._artifact(edge.downstream_artifact_id)
                if downstream.current_version_id != edge.downstream_version_id:
                    continue
                if downstream.id in visited:
                    continue
                visited.add(downstream.id)
                queue.append(downstream.id)
                result.append(
                    {
                        "artifact_id": downstream.id,
                        "artifact_kind": downstream.kind,
                        "artifact_name": downstream.name,
                        "dependency": self._dependency(edge),
                        "freshness": self.get_freshness(
                            downstream.id
                        ),
                    }
                )
        return result
