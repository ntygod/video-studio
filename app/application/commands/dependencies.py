"""Semantic command for registering Artifact derivation metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import ConflictError

from .base import CommandValidationError, OperationExecution


def _fingerprint(value: Any, prefix: str) -> dict[str, Any]:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        f"{prefix}_sha256": hashlib.sha256(encoded).hexdigest(),
        f"{prefix}_bytes": len(encoded),
    }


@dataclass(slots=True)
class RegisterArtifactDerivationCommand:
    output_version_id: str
    input_version_ids: list[str] = field(default_factory=list)
    input_asset_ids: list[str] = field(default_factory=list)
    dependency_type: str = "derived_from"
    asset_dependency_type: str = "uses_asset"
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    project_id: str | None = None
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "artifact.derivation.register"
    risk_level = "low"
    target_type = "artifact_version"

    @property
    def target_id(self) -> str:
        return self.output_version_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact-version:{self.output_version_id}:derivation"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "output_version_id": self.output_version_id,
            "input_version_ids": list(self.input_version_ids),
            "input_asset_ids": list(self.input_asset_ids),
            "dependency_type": self.dependency_type,
            "asset_dependency_type": self.asset_dependency_type,
            **_fingerprint(self.metadata, "metadata"),
            **_fingerprint(self.provenance, "provenance"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {
                "type": "artifact_version_exists",
                "version_id": self.output_version_id,
            }
        ]
        if self.input_version_ids:
            conditions.append(
                {
                    "type": "artifact_versions_exist",
                    "version_ids": list(self.input_version_ids),
                }
            )
        if self.input_asset_ids:
            conditions.append(
                {
                    "type": "assets_exist",
                    "asset_ids": list(self.input_asset_ids),
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        if not self.input_version_ids and not self.input_asset_ids:
            raise CommandValidationError(
                "derivation requires ArtifactVersion or Asset inputs"
            )
        output = uow.artifacts.get_version(
            self.output_version_id
        )
        artifact = uow.artifacts.get(output["artifact_id"])
        self.project_id = artifact["project_id"]
        for version_id in self.input_version_ids:
            version = uow.artifacts.get_version(version_id)
            upstream = uow.artifacts.get(version["artifact_id"])
            if upstream["project_id"] != self.project_id:
                raise ConflictError(
                    "artifact dependency cannot cross projects"
                )
        for asset_id in self.input_asset_ids:
            asset = uow.assets.get(asset_id)
            if asset["project_id"] != self.project_id:
                raise ConflictError(
                    "Asset dependency cannot cross projects"
                )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        uow.artifact_graph.register_derivation(
            self.output_version_id,
            self.input_version_ids,
            dependency_type=self.dependency_type,
            metadata=self.metadata,
            provenance={
                **self.provenance,
                "operation_id": self._operation_id or "",
            },
        )
        uow.artifact_graph.register_asset_dependencies(
            self.output_version_id,
            self.input_asset_ids,
            dependency_type=self.asset_dependency_type,
            metadata=self.metadata,
        )
        result = uow.artifact_graph.derivation(
            self.output_version_id
        )
        return OperationExecution(
            result=result,
            audit_result={
                "output_version_id": self.output_version_id
            },
            affected_entities=[
                {
                    "type": "artifact_version",
                    "id": self.output_version_id,
                },
                {
                    "type": "artifact",
                    "id": result["artifact_id"],
                },
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.artifact_graph.derivation(
            str((audit_result or {})["output_version_id"])
        )


__all__ = ["RegisterArtifactDerivationCommand"]
