"""Semantic Artifact commands."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import ConflictError

from .base import OperationExecution


def _payload_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded), "payload_keys": sorted(payload.keys())}


def _artifact_snapshot(artifact: dict[str, Any]) -> dict[str, Any]:
    return {key: artifact.get(key) for key in ("id", "project_id", "unit_id", "kind", "name", "schema_id", "current_version_id", "created_at", "updated_at")}


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

    operation_type = "artifact.create"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def arguments(self) -> dict[str, Any]:
        return {"unit_id": self.unit_id, "kind": self.kind, "name": self.name, "schema_id": self.schema_id, "schema_version": self.schema_version, "source": self.source, **_payload_fingerprint(self.payload)}

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "project_exists", "id": self.project_id}]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        uow.projects.get(self.project_id)
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                from app.store.repositories import NotFoundError
                raise NotFoundError(self.unit_id)
        artifact = uow.artifacts.create(project_id=self.project_id, unit_id=self.unit_id, kind=self.kind, name=self.name, schema_id=self.schema_id, payload=self.payload, source=self.source, schema_version=self.schema_version)
        version = artifact.get("current_version") or {}
        affected = [{"type": "artifact", "id": artifact["id"]}]
        if version.get("id"):
            affected.append({"type": "artifact_version", "id": version["id"]})
        return OperationExecution(
            result=artifact,
            audit_result={"artifact": _artifact_snapshot(artifact), "version_id": version.get("id")},
            affected_entities=affected,
            inverse_operation={"type": "artifact.delete_if_pristine", "artifact_id": artifact["id"], "version_id": version.get("id")},
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        stored = audit_result or {}
        artifact = dict(stored["artifact"])
        version_id = stored.get("version_id")
        if not version_id:
            return artifact
        version = uow.artifacts.get_version(str(version_id))
        return {**artifact, "current_version_id": version["id"], "current_version": version}


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
        return {"artifact_id": self.artifact_id, "source": self.source, "note": self.note, "schema_version": self.schema_version, "expected_current_version_id": self.expected_current_version_id, **_payload_fingerprint(self.payload)}

    def preconditions(self) -> list[dict[str, Any]]:
        conditions = [{"type": "artifact_exists", "id": self.artifact_id}]
        if self.expected_current_version_id:
            conditions.append({"type": "current_version_is", "id": self.expected_current_version_id})
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        artifact = uow.artifacts.get(self.artifact_id)
        self.project_id = artifact["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        artifact = uow.artifacts.get(self.artifact_id)
        current = artifact.get("current_version") or {}
        if self.expected_current_version_id and current.get("id") != self.expected_current_version_id:
            raise ConflictError("artifact current version changed")
        version = uow.artifacts.add_version(self.artifact_id, self.payload, source=self.source, note=self.note, schema_version=self.schema_version)
        return OperationExecution(
            result=version,
            audit_result={"artifact_id": self.artifact_id, "version_id": version["id"]},
            affected_entities=[{"type": "artifact", "id": self.artifact_id}, {"type": "artifact_version", "id": version["id"]}],
            inverse_operation={"type": "artifact.restore_version", "artifact_id": self.artifact_id, "version_id": current.get("id"), "created_version_id": version["id"]},
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        return uow.artifacts.get_version(str((audit_result or {})["version_id"]))


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
        return {"version_id": self.version_id, "status": self.status}

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "version_status_can_advance_to", "status": self.status}]

    def prepare(self, uow: UnitOfWork) -> None:
        version = uow.artifacts.get_version(self.version_id)
        artifact = uow.artifacts.get(version["artifact_id"])
        self.project_id = artifact["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        before = uow.artifacts.get_version(self.version_id)
        result = uow.artifacts.set_status(self.version_id, self.status)
        return OperationExecution(
            result=result,
            audit_result={"artifact_id": before["artifact_id"], "version_id": self.version_id, "status": result["status"]},
            affected_entities=[{"type": "artifact", "id": before["artifact_id"]}, {"type": "artifact_version", "id": self.version_id}],
            inverse_operation=None,
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        stored = audit_result or {}
        version = uow.artifacts.get_version(str(stored["version_id"]))
        if stored.get("status"):
            version["status"] = stored["status"]
        return version
