"""Semantic commands for durable jobs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.application.explicit_inputs import (
    resolve_explicit_job_inputs,
)
from app.application.jobs.runtime_contract import attach_runtime_job
from app.store import UnitOfWork
from app.store.repositories import NotFoundError

from .base import CommandValidationError, OperationExecution

INPUT_AWARE_JOB_TYPES = frozenset(
    {
        "generate",
        "llm",
        "media",
        "tts",
        "voice_synthesis",
        "render",
    }
)


def _semantic_value(value: Any) -> Any:
    """Remove tracing-only metadata from idempotency fingerprints."""

    if isinstance(value, dict):
        return {
            str(key): _semantic_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    return value


def _fingerprint(value: Any) -> dict[str, Any]:
    semantic = _semantic_value(value)
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "payload_bytes": len(encoded),
        "payload_keys": sorted(semantic.keys())
        if isinstance(semantic, dict)
        else [],
    }


@dataclass(slots=True)
class CreateJobCommand:
    project_id: str
    job_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    unit_id: str | None = None
    max_attempts: int = 3
    parent_job_id: str | None = None
    turn_id: str | None = None

    operation_type = "job.create"
    risk_level = "medium"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "job_type": self.job_type,
            "unit_id": self.unit_id,
            "max_attempts": self.max_attempts,
            "parent_job_id": self.parent_job_id,
            "turn_id": self.turn_id,
            **_fingerprint(self.payload),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "project_exists", "id": self.project_id}
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not str(self.job_type or "").strip():
            raise CommandValidationError(
                "job_type cannot be empty"
            )
        if self.max_attempts < 1:
            raise CommandValidationError(
                "max_attempts must be >= 1"
            )
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)
        if self.parent_job_id:
            parent = uow.jobs.get(self.parent_job_id)
            if parent["project_id"] != self.project_id:
                raise NotFoundError(self.parent_job_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        payload = deepcopy(self.payload)
        if (
            self.turn_id
            and self.job_type in INPUT_AWARE_JOB_TYPES
        ):
            input_version_ids, input_asset_ids = (
                resolve_explicit_job_inputs(
                    uow,
                    self.project_id,
                    self.turn_id,
                    payload,
                )
            )
            # Persist the exact resolved sets, including an explicit empty set
            # when a caller supplied input fields. This prevents a retry from
            # reinterpreting mutable Artifact "current" pointers.
            if (
                input_version_ids
                or "input_version_ids" in payload
                or "input_artifact_ids" in payload
            ):
                payload["input_version_ids"] = input_version_ids
            if input_asset_ids or "input_asset_ids" in payload:
                payload["input_asset_ids"] = input_asset_ids
            payload.pop("input_artifact_ids", None)

        job = uow.jobs.create(
            {
                "project_id": self.project_id,
                "unit_id": self.unit_id,
                "job_type": self.job_type,
                "payload": payload,
                "max_attempts": self.max_attempts,
                "parent_job_id": self.parent_job_id,
                "turn_id": self.turn_id,
            }
        )
        runtime = attach_runtime_job(uow, job)
        job = runtime["job"]
        affected = [{"type": "job", "id": job["id"]}]
        if runtime["plan"] is not None:
            affected.extend(
                [
                    {
                        "type": "runtime_plan",
                        "id": runtime["plan"]["id"],
                    },
                    {
                        "type": "runtime_task",
                        "id": runtime["task"]["id"],
                    },
                ]
            )
        return OperationExecution(
            result=job,
            audit_result={"job_id": job["id"]},
            affected_entities=affected,
            inverse_operation={
                "type": "job.cancel",
                "job_id": job["id"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.jobs.get(
            str((audit_result or {})["job_id"])
        )


__all__ = ["CreateJobCommand", "INPUT_AWARE_JOB_TYPES"]
