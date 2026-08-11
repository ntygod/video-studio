"""Semantic commands for timeline compilation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.application.timeline_service import (
    compile_timeline,
    pick_edit_plan_artifact,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

from .base import CommandValidationError, OperationExecution


def _fingerprint(parameters: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "parameters_sha256": hashlib.sha256(encoded).hexdigest(),
        "parameters_bytes": len(encoded),
        "parameter_keys": sorted(parameters),
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


def _timeline_asset_ids(timeline: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for track in timeline.get("tracks") or []:
        for clip in track.get("clips") or []:
            asset_id = str(clip.get("asset_id") or "")
            if asset_id and asset_id not in result:
                result.append(asset_id)
    return result


@dataclass(slots=True)
class CompileTimelineCommand:
    project_id: str
    unit_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    input_version_ids: list[str] = field(default_factory=list)
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "timeline.compile"
    risk_level = "medium"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        scope = self.unit_id or "project"
        return f"timeline:{self.project_id}:{scope}"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "input_version_ids": list(self.input_version_ids),
            **_fingerprint(self.parameters),
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
        if self.input_version_ids:
            conditions.append(
                {
                    "type": "artifact_versions_belong_to_project",
                    "version_ids": list(self.input_version_ids),
                    "project_id": self.project_id,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not isinstance(self.parameters, dict):
            raise CommandValidationError(
                "timeline parameters must be an object"
            )
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)
        for version_id in self.input_version_ids:
            version = uow.artifacts.get_version(version_id)
            artifact = uow.artifacts.get(version["artifact_id"])
            if artifact["project_id"] != self.project_id:
                raise ConflictError(
                    "timeline input belongs to another project"
                )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id:
            raise RuntimeError(
                "timeline command is not bound to an operation"
            )
        artifacts = uow.artifacts.list(
            self.project_id,
            unit_id=self.unit_id,
        )
        edit_plan = pick_edit_plan_artifact(artifacts)
        timeline = compile_timeline(
            uow,
            self.project_id,
            self.unit_id,
            self.parameters,
            selected_edit_plan=edit_plan,
        )
        artifact = uow.artifacts.find_latest(
            self.project_id,
            self.unit_id,
            "timeline",
        )
        if artifact is None:
            saved = uow.artifacts.create(
                project_id=self.project_id,
                unit_id=self.unit_id,
                kind="timeline",
                name="时间线",
                schema_id="video-studio/timeline@1",
                payload=timeline,
                source="system",
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
                timeline,
                source="system",
                note="重新编译时间线",
            )
            saved = uow.artifacts.get(artifact["id"])
            inverse = {
                "type": "artifact.restore_version",
                "artifact_id": artifact["id"],
                "version_id": previous.get("id"),
                "created_version_id": version["id"],
            }

        automatic_inputs: list[str] = []
        if edit_plan:
            edit_version_id = str(
                (edit_plan.get("current_version") or {}).get("id")
                or ""
            )
            if edit_version_id:
                automatic_inputs.append(edit_version_id)
        inputs = list(
            dict.fromkeys(
                [*self.input_version_ids, *automatic_inputs]
            )
        )
        asset_ids = _timeline_asset_ids(timeline)
        uow.artifact_graph.register_derivation(
            str(version["id"]),
            inputs,
            dependency_type="compiled_from",
            metadata={
                "asset_ids": asset_ids,
                "edit_plan_artifact_id": (
                    edit_plan.get("id") if edit_plan else None
                ),
            },
            provenance={
                "prompt_version": "timeline-compiler@1",
                "parameters": {
                    "compile_parameters": deepcopy(self.parameters),
                    "asset_ids": asset_ids,
                },
                "operation_id": self._operation_id,
            },
        )

        snapshot = _artifact_snapshot(saved)
        return OperationExecution(
            result={"timeline": timeline, "artifact": saved},
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
        stored = audit_result or {}
        version = uow.artifacts.get_version(
            str(stored["version_id"])
        )
        artifact = dict(stored["artifact"])
        artifact.update(
            {
                "current_version_id": version["id"],
                "current_version": version,
            }
        )
        return {
            "timeline": version["payload"],
            "artifact": artifact,
        }


__all__ = ["CompileTimelineCommand"]
