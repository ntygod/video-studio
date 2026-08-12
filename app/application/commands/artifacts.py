"""Semantic Artifact commands."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.application.explicit_inputs import (
    resolve_explicit_job_inputs,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

from .base import OperationExecution


def _payload_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "payload_bytes": len(encoded),
        "payload_keys": sorted(payload.keys()),
    }


def _value_fingerprint(
    value: Any,
    prefix: str,
) -> dict[str, Any]:
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


def _artifact_snapshot(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: artifact.get(key)
        for key in (
            "id",
            "project_id",
            "unit_id",
            "kind",
            "name",
            "schema_id",
            "current_version_id",
            "created_at",
            "updated_at",
        )
    }


@dataclass(slots=True)
class CreateArtifactCommand:
    project_id: str
    unit_id: str | None
    kind: str
    name: str
    schema_id: str
    payload: dict[str, Any]
    source: str = "user"
    schema_version: int | None = None
    input_context_turn_id: str | None = None
    input_version_ids: list[str] = field(default_factory=list)
    input_artifact_ids: list[str] = field(default_factory=list)
    input_asset_ids: list[str] = field(default_factory=list)
    dependency_type: str = "derived_from"
    asset_dependency_type: str = "uses_asset"
    dependency_metadata: dict[str, Any] = field(
        default_factory=dict
    )
    provenance: dict[str, Any] = field(default_factory=dict)
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "artifact.create"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def _has_explicit_inputs(self) -> bool:
        return bool(
            self.input_context_turn_id
            or self.input_version_ids
            or self.input_artifact_ids
            or self.input_asset_ids
        )

    def arguments(self) -> dict[str, Any]:
        arguments = {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "source": self.source,
            **_payload_fingerprint(self.payload),
        }
        # Keep the historical command fingerprint unchanged for ordinary
        # Artifact creation. Input fields are added only for input-aware writes.
        if self._has_explicit_inputs() or self.provenance:
            arguments.update(
                {
                    "input_context_turn_id": self.input_context_turn_id,
                    "input_version_ids": list(self.input_version_ids),
                    "input_artifact_ids": list(self.input_artifact_ids),
                    "input_asset_ids": list(self.input_asset_ids),
                    "dependency_type": self.dependency_type,
                    "asset_dependency_type": self.asset_dependency_type,
                    **_value_fingerprint(
                        self.dependency_metadata,
                        "dependency_metadata",
                    ),
                    **_value_fingerprint(
                        self.provenance,
                        "provenance",
                    ),
                }
            )
        return arguments

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {"type": "project_exists", "id": self.project_id}
        ]
        if self.input_context_turn_id:
            conditions.append(
                {
                    "type": "agent_turn_belongs_to_project",
                    "turn_id": self.input_context_turn_id,
                    "project_id": self.project_id,
                }
            )
        if self._has_explicit_inputs():
            conditions.append(
                {"type": "explicit_inputs_are_readable"}
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        requested_inputs = {
            "input_version_ids": list(self.input_version_ids),
            "input_artifact_ids": list(self.input_artifact_ids),
            "input_asset_ids": list(self.input_asset_ids),
        }
        if self._has_explicit_inputs():
            resolved_versions, resolved_assets = (
                resolve_explicit_job_inputs(
                    uow,
                    self.project_id,
                    self.input_context_turn_id,
                    requested_inputs,
                )
            )
        else:
            resolved_versions, resolved_assets = [], []

        artifact = uow.artifacts.create(
            project_id=self.project_id,
            unit_id=self.unit_id,
            kind=self.kind,
            name=self.name,
            schema_id=self.schema_id,
            payload=self.payload,
            source=self.source,
            schema_version=self.schema_version,
        )
        version = artifact.get("current_version") or {}
        version_id = str(version.get("id") or "")

        derivation = None
        asset_dependencies: list[dict[str, Any]] = []
        if (
            version_id
            and (
                self._has_explicit_inputs()
                or self.provenance
            )
        ):
            if not self._operation_id:
                raise RuntimeError(
                    "input-aware Artifact command is not bound to an operation"
                )
            metadata = {
                **deepcopy(self.dependency_metadata),
                "source": self.source,
            }
            if self.input_context_turn_id:
                metadata.setdefault(
                    "turn_id",
                    self.input_context_turn_id,
                )
            provenance = {
                **deepcopy(self.provenance),
                "operation_id": self._operation_id,
            }
            if self.input_context_turn_id:
                provenance.setdefault(
                    "task_attempt_id",
                    f"agent-turn:{self.input_context_turn_id}",
                )
            derivation = uow.artifact_graph.register_derivation(
                version_id,
                resolved_versions,
                dependency_type=self.dependency_type,
                metadata=metadata,
                provenance=provenance,
            )
            asset_dependencies = (
                uow.artifact_graph.register_asset_dependencies(
                    version_id,
                    resolved_assets,
                    dependency_type=self.asset_dependency_type,
                    metadata=metadata,
                )
            )

        affected = [
            {"type": "artifact", "id": artifact["id"]}
        ]
        if version_id:
            affected.append(
                {"type": "artifact_version", "id": version_id}
            )
        if derivation is not None:
            affected.extend(
                {
                    "type": "artifact_dependency",
                    "id": edge["id"],
                }
                for edge in derivation.get("dependencies") or []
            )
        affected.extend(
            {
                "type": "asset_dependency",
                "id": edge["id"],
            }
            for edge in asset_dependencies
        )

        return OperationExecution(
            result=artifact,
            audit_result={
                "artifact": _artifact_snapshot(artifact),
                "version_id": version.get("id"),
                "input_version_ids": resolved_versions,
                "input_asset_ids": resolved_assets,
            },
            affected_entities=affected,
            inverse_operation={
                "type": "artifact.delete_if_pristine",
                "artifact_id": artifact["id"],
                "version_id": version.get("id"),
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        stored = audit_result or {}
        artifact = dict(stored["artifact"])
        version_id = stored.get("version_id")
        if not version_id:
            return artifact
        version = uow.artifacts.get_version(str(version_id))
        return {
            **artifact,
            "current_version_id": version["id"],
            "current_version": version,
        }


@dataclass(slots=True)
class AddArtifactVersionCommand:
    artifact_id: str
    payload: dict[str, Any]
    source: str = "user"
    note: str = ""
    schema_version: int | None = None
    expected_current_version_id: str | None = None
    project_id: str | None = None

    operation_type = "artifact.version.add"
    risk_level = "medium"
    target_type = "artifact"

    @property
    def target_id(self) -> str:
        return self.artifact_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact:{self.artifact_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source": self.source,
            "note": self.note,
            "schema_version": self.schema_version,
            "expected_current_version_id": (
                self.expected_current_version_id
            ),
            **_payload_fingerprint(self.payload),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions = [
            {"type": "artifact_exists", "id": self.artifact_id}
        ]
        if self.expected_current_version_id:
            conditions.append(
                {
                    "type": "current_version_is",
                    "id": self.expected_current_version_id,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        artifact = uow.artifacts.get(self.artifact_id)
        self.project_id = artifact["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        artifact = uow.artifacts.get(self.artifact_id)
        current = artifact.get("current_version") or {}
        if (
            self.expected_current_version_id
            and current.get("id")
            != self.expected_current_version_id
        ):
            raise ConflictError("artifact current version changed")
        version = uow.artifacts.add_version(
            self.artifact_id,
            self.payload,
            source=self.source,
            note=self.note,
            schema_version=self.schema_version,
        )
        return OperationExecution(
            result=version,
            audit_result={
                "artifact_id": self.artifact_id,
                "version_id": version["id"],
            },
            affected_entities=[
                {"type": "artifact", "id": self.artifact_id},
                {
                    "type": "artifact_version",
                    "id": version["id"],
                },
            ],
            inverse_operation={
                "type": "artifact.restore_version",
                "artifact_id": self.artifact_id,
                "version_id": current.get("id"),
                "created_version_id": version["id"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.artifacts.get_version(
            str((audit_result or {})["version_id"])
        )


@dataclass(slots=True)
class SetArtifactVersionStatusCommand:
    version_id: str
    status: str
    project_id: str | None = None

    operation_type = "artifact.version.status.set"
    risk_level = "high"
    target_type = "artifact_version"

    @property
    def target_id(self) -> str:
        return self.version_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact_version:{self.version_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "status": self.status,
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "version_status_can_advance_to",
                "status": self.status,
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        version = uow.artifacts.get_version(self.version_id)
        artifact = uow.artifacts.get(version["artifact_id"])
        self.project_id = artifact["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        before = uow.artifacts.get_version(self.version_id)
        result = uow.artifacts.set_status(
            self.version_id,
            self.status,
        )
        return OperationExecution(
            result=result,
            audit_result={
                "artifact_id": before["artifact_id"],
                "version_id": self.version_id,
                "status": result["status"],
            },
            affected_entities=[
                {
                    "type": "artifact",
                    "id": before["artifact_id"],
                },
                {
                    "type": "artifact_version",
                    "id": self.version_id,
                },
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        stored = audit_result or {}
        version = uow.artifacts.get_version(
            str(stored["version_id"])
        )
        if stored.get("status"):
            version["status"] = stored["status"]
        return version
