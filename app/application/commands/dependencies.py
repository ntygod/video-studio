"""Semantic command for registering Artifact derivation metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.store import UnitOfWork

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
    input_version_ids: list[str]
    dependency_type: str = "derived_from"
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    project_id: str | None = None

    operation_type = "artifact.derivation.register"
    risk_level = "low"
    target_type = "artifact_version"

    @property
    def target_id(self) -> str:
        return self.output_version_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact-version:{self.output_version_id}:derivation"

    def arguments(self) -> dict[str, Any]:
        return {
            "output_version_id": self.output_version_id,
            "input_version_ids": list(self.input_version_ids),
            "dependency_type": self.dependency_type,
            **_fingerprint(self.metadata, "metadata"),
            **_fingerprint(self.provenance, "provenance"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "artifact_versions_exist",
                "version_ids": [
                    *self.input_version_ids,
                    self.output_version_id,
                ],
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        if not self.input_version_ids:
            raise CommandValidationError(
                "derivation requires input_version_ids"
            )
        output = uow.artifacts.get_version(
            self.output_version_id
        )
        artifact = uow.artifacts.get(output["artifact_id"])
        self.project_id = artifact["project_id"]
        for version_id in self.input_version_ids:
            uow.artifacts.get_version(version_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        result = uow.artifact_graph.register_derivation(
            self.output_version_id,
            self.input_version_ids,
            dependency_type=self.dependency_type,
            metadata=self.metadata,
            provenance=self.provenance,
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
