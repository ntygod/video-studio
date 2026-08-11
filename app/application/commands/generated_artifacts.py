"""Durable, job-scoped persistence of generated Artifact payloads."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.store import UnitOfWork
from app.store.operation_models import OperationLogRow
from app.store.repositories import NotFoundError

from .base import CommandValidationError, OperationExecution

SINGLETON_GENERATED_KINDS = frozenset({"edit_plan", "timeline"})


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
        "payload_keys": sorted(payload),
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
    """Return an already persisted output or the next attempt key.

    A Job may crash after its Artifact transaction commits but before the Job
    result is updated. Any succeeded persistence operation is authoritative and
    is replayed before another model call. Failed operations remain auditable
    and receive a new numbered key on the next retry.
    """

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

    operation_type = "artifact.generated.persist"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        unit = self.unit_id or "project"
        return f"project:{self.project_id}:{unit}:{self.kind}"

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "schema_id": self.schema_id,
            "source": self.source,
            **_payload_fingerprint(self.payload),
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
        return conditions

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

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        artifact = None
        if self.kind in SINGLETON_GENERATED_KINDS:
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
                note=f"重新生成{self.name}",
            )
            saved = uow.artifacts.get(artifact["id"])
            inverse = {
                "type": "artifact.restore_version",
                "artifact_id": artifact["id"],
                "version_id": previous.get("id"),
                "created_version_id": version["id"],
            }

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
