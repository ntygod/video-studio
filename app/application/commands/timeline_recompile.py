"""Optimistically recompile one stale Timeline Artifact."""

from __future__ import annotations

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
class RecompileTimelineArtifactCommand:
    artifact_id: str
    expected_current_version_id: str
    project_id: str | None = None
    _unit_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _parameters: dict[str, Any] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _input_version_ids: list[str] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "timeline.recompile"
    risk_level = "medium"
    target_type = "artifact"

    @property
    def target_id(self) -> str:
        return self.artifact_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact:{self.artifact_id}:timeline-recompile"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "expected_current_version_id": (
                self.expected_current_version_id
            ),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "artifact_exists", "id": self.artifact_id},
            {
                "type": "current_version_is",
                "id": self.expected_current_version_id,
            },
            {
                "type": "artifact_kind_is",
                "kind": "timeline",
            },
            {
                "type": "timeline_inputs_are_available",
            },
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        artifact = uow.artifacts.get(self.artifact_id)
        if artifact["kind"] != "timeline":
            raise CommandValidationError(
                "only Timeline Artifacts can be recompiled"
            )
        self.project_id = artifact["project_id"]
        self._unit_id = artifact.get("unit_id")
        current = artifact.get("current_version") or {}
        if current.get("id") != self.expected_current_version_id:
            raise ConflictError(
                "Timeline changed after recompilation was planned"
            )
        if current.get("status") == "locked":
            raise ConflictError(
                "locked Timeline cannot receive a recompiled version"
            )
        freshness = uow.artifact_graph.get_freshness(
            self.artifact_id
        )
        if freshness["status"] not in {"stale", "blocked"}:
            raise ConflictError(
                "only a stale or blocked Timeline needs recompilation"
            )

        asset_dependencies = (
            uow.artifact_graph.asset_dependencies_for_version(
                self.expected_current_version_id
            )
        )
        missing = [
            str(item["upstream_asset_id"])
            for item in asset_dependencies
            if not item.get("asset_exists")
        ]
        if missing:
            raise ConflictError(
                "Timeline has missing Asset inputs and requires replacements: "
                + ", ".join(sorted(missing))
            )

        provenance = uow.artifact_graph.provenance(
            self.expected_current_version_id
        ) or {}
        refreshed_inputs: list[str] = []
        for old_version_id in provenance.get("input_version_ids") or []:
            try:
                old_version = uow.artifacts.get_version(
                    str(old_version_id)
                )
                upstream = uow.artifacts.get(
                    old_version["artifact_id"]
                )
            except NotFoundError as exc:
                raise ConflictError(
                    "Timeline has a deleted upstream Artifact version"
                ) from exc
            if upstream["project_id"] != self.project_id:
                raise ConflictError(
                    "Timeline input belongs to another project"
                )
            upstream_freshness = uow.artifact_graph.get_freshness(
                upstream["id"]
            )
            if upstream_freshness["status"] != "fresh":
                raise ConflictError(
                    f"upstream Artifact {upstream['name']} is not fresh"
                )
            current_id = str(
                upstream.get("current_version_id") or ""
            )
            if not current_id:
                raise ConflictError(
                    f"upstream Artifact {upstream['name']} has no current version"
                )
            if current_id not in refreshed_inputs:
                refreshed_inputs.append(current_id)
        self._input_version_ids = refreshed_inputs

        parameters = deepcopy(
            (provenance.get("parameters") or {}).get(
                "compile_parameters"
            )
            or {}
        )
        current_payload = current.get("payload") or {}
        for key in ("width", "height", "fps"):
            if key in current_payload:
                parameters.setdefault(key, current_payload[key])
        self._parameters = parameters

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id or not self.project_id:
            raise RuntimeError(
                "Timeline recompile command is not prepared"
            )
        artifact = uow.artifacts.get(self.artifact_id)
        current = artifact.get("current_version") or {}
        if current.get("id") != self.expected_current_version_id:
            raise ConflictError(
                "Timeline changed while recompilation was running"
            )

        artifacts = uow.artifacts.list(
            self.project_id,
            unit_id=self._unit_id,
        )
        edit_plan = pick_edit_plan_artifact(artifacts)
        timeline = compile_timeline(
            uow,
            self.project_id,
            self._unit_id,
            self._parameters,
            selected_edit_plan=edit_plan,
        )
        version = uow.artifacts.add_version(
            self.artifact_id,
            timeline,
            source="system",
            note="按最新输入重新编译时间线",
        )
        saved = uow.artifacts.get(self.artifact_id)

        inputs = list(self._input_version_ids)
        if edit_plan:
            edit_version_id = str(
                (edit_plan.get("current_version") or {}).get("id")
                or ""
            )
            if edit_version_id and edit_version_id not in inputs:
                inputs.append(edit_version_id)
        asset_ids = _timeline_asset_ids(timeline)
        metadata = {
            "recompiled_version_id": self.expected_current_version_id,
            "asset_ids": asset_ids,
            "edit_plan_artifact_id": (
                edit_plan.get("id") if edit_plan else None
            ),
        }
        uow.artifact_graph.register_derivation(
            str(version["id"]),
            inputs,
            dependency_type="recompiled_from",
            metadata=metadata,
            provenance={
                "prompt_version": "timeline-recompile@1",
                "parameters": {
                    "compile_parameters": deepcopy(self._parameters),
                    "asset_ids": asset_ids,
                },
                "operation_id": self._operation_id,
            },
        )
        uow.artifact_graph.register_asset_dependencies(
            str(version["id"]),
            asset_ids,
            dependency_type="timeline_clip",
            metadata={
                "role": "timeline_clip",
                "recompiled_version_id": (
                    self.expected_current_version_id
                ),
            },
        )

        snapshot = _artifact_snapshot(saved)
        return OperationExecution(
            result={"timeline": timeline, "artifact": saved},
            audit_result={
                "artifact": snapshot,
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
                "version_id": self.expected_current_version_id,
                "created_version_id": version["id"],
            },
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


__all__ = ["RecompileTimelineArtifactCommand"]
