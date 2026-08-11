"""Durable, job-scoped persistence of generated Artifact payloads."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.store import UnitOfWork
from app.store.operation_models import OperationLogRow
from app.store.repositories import ConflictError, NotFoundError

from .base import CommandValidationError, OperationExecution

SINGLETON_GENERATED_KINDS = frozenset({"edit_plan", "timeline"})


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


def _replay_from_audit(
    uow: UnitOfWork,
    audit_result: dict[str, Any],
) -> dict[str, Any]:
    version = uow.artifacts.get_version(
        str(audit_result["version_id"])
    )
    artifact = dict(audit_result["artifact"])
    artifact.update(
        {
            "current_version_id": version["id"],
            "current_version": version,
        }
    )
    return artifact


def generated_artifact_attempt(
    database,
    job_id: str,
) -> tuple[dict[str, Any] | None, str]:
    with UnitOfWork(database) as uow:
        rows = uow.session.scalars(
            select(OperationLogRow)
            .where(
                OperationLogRow.operation_type
                == "artifact.generated.persist",
                OperationLogRow.actor_type == "job",
                OperationLogRow.actor_id == job_id,
            )
            .order_by(
                OperationLogRow.created_at,
                OperationLogRow.id,
            )
        ).all()
        for row in rows:
            if row.status != "succeeded":
                continue
            operation = uow.operations.get(row.id)
            return (
                _replay_from_audit(
                    uow,
                    operation.get("result") or {},
                ),
                str(row.idempotency_key or ""),
            )
        running = next(
            (row for row in reversed(rows) if row.status == "running"),
            None,
        )
        if running is not None and running.idempotency_key:
            return None, str(running.idempotency_key)
        return None, f"job:{job_id}:artifact:{len(rows) + 1}"


@dataclass(slots=True)
class PersistGeneratedArtifactCommand:
    project_id: str
    payload: dict[str, Any]
    unit_id: str | None = None
    kind: str = "generated"
    name: str = "AI 生成"
    schema_id: str = "freeform"
    source: str = "job"
    input_version_ids: list[str] = field(default_factory=list)
    dependency_type: str = "generated_from"
    dependency_metadata: dict[str, Any] = field(
        default_factory=dict
    )
    provenance: dict[str, Any] = field(default_factory=dict)
    target_artifact_id: str | None = None
    expected_target_version_id: str | None = None
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "artifact.generated.persist"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.target_artifact_id or self.project_id

    @property
    def idempotency_scope(self) -> str:
        if self.target_artifact_id:
            return (
                f"artifact:{self.target_artifact_id}:generated-version"
            )
        unit = self.unit_id or "project"
        return f"project:{self.project_id}:{unit}:{self.kind}"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "schema_id": self.schema_id,
            "source": self.source,
            "target_artifact_id": self.target_artifact_id,
            "expected_target_version_id": (
                self.expected_target_version_id
            ),
            "input_version_ids": list(self.input_version_ids),
            "dependency_type": self.dependency_type,
            **_fingerprint(self.payload, "payload"),
            **_fingerprint(
                self.dependency_metadata,
                "dependency_metadata",
            ),
            **_fingerprint(self.provenance, "provenance"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {"type": "project_exists", "id": self.project_id}
        ]
        if self.unit_id:
            conditions.append(
                {
                    "type": "unit_belongs_to_project",
                    "unit_id": self.unit_id,
                    "project_id": self.project_id,
                }
            )
        if self.target_artifact_id:
            conditions.append(
                {
                    "type": "artifact_belongs_to_project",
                    "artifact_id": self.target_artifact_id,
                    "project_id": self.project_id,
                }
            )
        if self.expected_target_version_id:
            conditions.append(
                {
                    "type": "current_version_is",
                    "id": self.expected_target_version_id,
                }
            )
        if self.input_version_ids:
            conditions.append(
                {
                    "type": "artifact_versions_belong_to_project",
                    "version_ids": list(self.input_version_ids),
                    "project_id": self.project_id,
                }
            )
        return conditions

    def _target_artifact(
        self,
        uow: UnitOfWork,
    ) -> dict[str, Any] | None:
        if not self.target_artifact_id:
            return None
        artifact = uow.artifacts.get(self.target_artifact_id)
        if artifact["project_id"] != self.project_id:
            raise ConflictError(
                "generated Artifact target belongs to another project"
            )
        if artifact.get("unit_id") != self.unit_id:
            raise ConflictError(
                "generated Artifact target scope changed"
            )
        if artifact["kind"] != self.kind:
            raise ConflictError(
                "generated Artifact target kind changed"
            )
        if artifact["schema_id"] != self.schema_id:
            raise ConflictError(
                "generated Artifact target schema changed"
            )
        current = artifact.get("current_version") or {}
        if (
            self.expected_target_version_id
            and current.get("id")
            != self.expected_target_version_id
        ):
            raise ConflictError(
                "target Artifact changed while regeneration was running"
            )
        if current.get("status") == "locked":
            raise ConflictError(
                "locked Artifact cannot receive a generated version"
            )
        return artifact

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not isinstance(self.payload, dict):
            raise CommandValidationError(
                "generated Artifact payload must be an object"
            )
        if not str(self.kind or "").strip():
            raise CommandValidationError(
                "generated Artifact kind cannot be empty"
            )
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)
        self._target_artifact(uow)
        for version_id in self.input_version_ids:
            version = uow.artifacts.get_version(version_id)
            artifact = uow.artifacts.get(version["artifact_id"])
            if artifact["project_id"] != self.project_id:
                raise ConflictError(
                    "generated Artifact input belongs to another project"
                )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id:
            raise RuntimeError(
                "generated Artifact command is not bound to an operation"
            )
        artifact = self._target_artifact(uow)
        if artifact is None and self.kind in SINGLETON_GENERATED_KINDS:
            artifact = uow.artifacts.find_latest(
                self.project_id,
                self.unit_id,
                self.kind,
            )

        if artifact is None:
            saved = uow.artifacts.create(
                project_id=self.project_id,
                unit_id=self.unit_id,
                kind=self.kind,
                name=self.name,
                schema_id=self.schema_id,
                payload=self.payload,
                source=self.source,
            )
            version = saved.get("current_version") or {}
            inverse = {
                "type": "artifact.delete_if_pristine",
                "artifact_id": saved["id"],
                "version_id": version.get("id"),
            }
        else:
            previous = artifact.get("current_version") or {}
            version = uow.artifacts.add_version(
                artifact["id"],
                self.payload,
                source=self.source,
                note=(
                    f"重新生成{artifact['name']}"
                    if self.target_artifact_id
                    else f"重新生成{self.name}"
                ),
            )
            saved = uow.artifacts.get(artifact["id"])
            inverse = {
                "type": "artifact.restore_version",
                "artifact_id": artifact["id"],
                "version_id": previous.get("id"),
                "created_version_id": version["id"],
            }

        uow.artifact_graph.register_derivation(
            str(version["id"]),
            self.input_version_ids,
            dependency_type=self.dependency_type,
            metadata=deepcopy(self.dependency_metadata),
            provenance={
                **deepcopy(self.provenance),
                "operation_id": self._operation_id,
            },
        )
        snapshot = _artifact_snapshot(saved)
        return OperationExecution(
            result=saved,
            audit_result={
                "artifact": snapshot,
                "version_id": version.get("id"),
            },
            affected_entities=[
                {"type": "artifact", "id": saved["id"]},
                {
                    "type": "artifact_version",
                    "id": str(version.get("id") or ""),
                },
            ],
            inverse_operation=inverse,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return _replay_from_audit(
            uow,
            deepcopy(audit_result or {}),
        )


__all__ = [
    "PersistGeneratedArtifactCommand",
    "SINGLETON_GENERATED_KINDS",
    "generated_artifact_attempt",
]
