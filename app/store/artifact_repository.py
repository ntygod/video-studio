"""Artifact repository boundary with schema-aware writes."""

from __future__ import annotations

import time
from typing import Any

from app.domain.artifact_registry import artifact_definitions

from .dependency_repository import ArtifactGraphRepository
from .models import ArtifactRow, ArtifactVersionRow
from .repositories import ArtifactRepository, NotFoundError, new_id


class SchemaAwareArtifactRepository(ArtifactRepository):
    """Validate every Artifact write, regardless of its API or Agent origin."""

    def create(
        self,
        project_id: str,
        unit_id: str | None,
        kind: str,
        name: str,
        schema_id: str,
        payload: dict[str, Any],
        source: str = "user",
        schema_version: int | None = None,
    ) -> dict[str, Any]:
        validated = artifact_definitions.validate(
            kind,
            payload,
            schema_id=schema_id,
            schema_version=schema_version,
        )
        now = time.time()
        artifact = ArtifactRow(
            id=new_id(),
            project_id=project_id,
            unit_id=unit_id,
            kind=kind,
            name=name,
            schema_id=validated.schema_id,
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(artifact)
        self.session.flush()
        version = self.add_version(
            artifact.id,
            validated.payload,
            source=source,
            schema_version=validated.schema_version,
        )
        return {
            **self._artifact(artifact),
            "current_version": version,
        }

    def add_version(
        self,
        artifact_id: str,
        payload: dict[str, Any],
        source: str = "user",
        status: str = "draft",
        parent_version_id: str | None = None,
        note: str = "",
        schema_version: int | None = None,
    ) -> dict[str, Any]:
        artifact = self.session.get(ArtifactRow, artifact_id)
        if artifact is None:
            raise NotFoundError(artifact_id)
        validated = artifact_definitions.validate(
            artifact.kind,
            payload,
            schema_id=artifact.schema_id,
            schema_version=schema_version,
        )
        if artifact.schema_id != validated.schema_id:
            artifact.schema_id = validated.schema_id
        created = super().add_version(
            artifact_id,
            validated.payload,
            source=source,
            status=status,
            parent_version_id=parent_version_id,
            note=note,
        )
        row = self.session.get(ArtifactVersionRow, created["id"])
        if row is None:
            raise RuntimeError(
                "artifact version disappeared after creation"
            )
        row.schema_version = validated.schema_version
        self.session.flush()
        ArtifactGraphRepository(self.session).on_new_version(
            artifact_id,
            row.id,
        )
        return self._version(row)
