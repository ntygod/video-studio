"""Repair a blocked Timeline by replacing every missing Asset input."""

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

_VISUAL_KINDS = frozenset({"image", "video"})


def _fingerprint(value: Any) -> dict[str, Any]:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "replacements_sha256": hashlib.sha256(encoded).hexdigest(),
        "replacement_count": len(value),
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


def _compatible_asset_kind(old_kind: str, new_kind: str) -> bool:
    if old_kind == new_kind:
        return True
    return old_kind in _VISUAL_KINDS and new_kind in _VISUAL_KINDS


@dataclass(slots=True)
class RepairTimelineAssetsCommand:
    artifact_id: str
    replacements: dict[str, str]
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

    operation_type = "timeline.assets.repair"
    risk_level = "medium"
    target_type = "artifact"

    @property
    def target_id(self) -> str:
        return self.artifact_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact:{self.artifact_id}:repair-assets"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "expected_current_version_id": (
                self.expected_current_version_id
            ),
            "replacements": dict(sorted(self.replacements.items())),
            **_fingerprint(self.replacements),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "artifact_exists", "id": self.artifact_id},
            {
                "type": "current_version_is",
                "id": self.expected_current_version_id,
            },
            {"type": "artifact_freshness_is", "status": "blocked"},
            {"type": "all_missing_assets_are_replaced"},
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        if not isinstance(self.replacements, dict) or not self.replacements:
            raise CommandValidationError(
                "timeline repair requires Asset replacements"
            )
        replacements = {
            str(source): str(target)
            for source, target in self.replacements.items()
            if str(source) and str(target)
        }
        if len(replacements) != len(self.replacements):
            raise CommandValidationError(
                "timeline Asset replacements cannot contain empty ids"
            )
        if len(set(replacements.values())) != len(replacements):
            raise CommandValidationError(
                "each missing Asset needs a distinct replacement"
            )
        self.replacements = replacements

        artifact = uow.artifacts.get(self.artifact_id)
        if artifact["kind"] != "timeline":
            raise CommandValidationError(
                "Asset repair is currently supported only for Timeline Artifacts"
            )
        self.project_id = artifact["project_id"]
        self._unit_id = artifact.get("unit_id")
        current = artifact.get("current_version") or {}
        current_version_id = str(current.get("id") or "")
        if current_version_id != self.expected_current_version_id:
            raise ConflictError(
                "Timeline changed after Asset repair was requested"
            )
        if current.get("status") == "locked":
            raise ConflictError(
                "locked Timeline cannot receive a repaired version"
            )
        freshness = uow.artifact_graph.get_freshness(
            self.artifact_id
        )
        if freshness["status"] != "blocked":
            raise ConflictError(
                "only a blocked Timeline can repair missing Assets"
            )

        dependencies = (
            uow.artifact_graph.asset_dependencies_for_version(
                current_version_id
            )
        )
        missing = {
            str(item["upstream_asset_id"]): item
            for item in dependencies
            if not item.get("asset_exists")
        }
        if not missing:
            raise ConflictError(
                "Timeline is not blocked by missing Asset inputs"
            )
        replacement_keys = set(replacements)
        missing_keys = set(missing)
        if replacement_keys != missing_keys:
            omitted = sorted(missing_keys - replacement_keys)
            unexpected = sorted(replacement_keys - missing_keys)
            details = []
            if omitted:
                details.append("missing mappings: " + ", ".join(omitted))
            if unexpected:
                details.append(
                    "unexpected mappings: " + ", ".join(unexpected)
                )
            raise CommandValidationError("; ".join(details))

        for missing_id, replacement_id in replacements.items():
            try:
                replacement = uow.assets.get(replacement_id)
            except NotFoundError as exc:
                raise CommandValidationError(
                    f"replacement Asset does not exist: {replacement_id}"
                ) from exc
            if replacement["project_id"] != self.project_id:
                raise ConflictError(
                    "replacement Asset belongs to another project"
                )
            snapshot = missing[missing_id].get("upstream_asset") or {}
            if replacement.get("unit_id") != snapshot.get("unit_id"):
                raise ConflictError(
                    "replacement Asset must keep the original Unit scope"
                )
            old_kind = str(snapshot.get("kind") or "")
            new_kind = str(replacement.get("kind") or "")
            if not _compatible_asset_kind(old_kind, new_kind):
                raise ConflictError(
                    f"replacement Asset kind is incompatible: {old_kind} -> {new_kind}"
                )

        provenance = uow.artifact_graph.provenance(
            current_version_id
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
                    "Timeline also has a deleted upstream Artifact"
                ) from exc
            upstream_freshness = uow.artifact_graph.get_freshness(
                upstream["id"]
            )
            if upstream_freshness["status"] != "fresh":
                raise ConflictError(
                    f"upstream Artifact {upstream['name']} is not fresh"
                )
            refreshed_id = str(
                upstream.get("current_version_id") or ""
            )
            if not refreshed_id:
                raise ConflictError(
                    f"upstream Artifact {upstream['name']} has no current version"
                )
            if refreshed_id not in refreshed_inputs:
                refreshed_inputs.append(refreshed_id)
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
        parameters["asset_replacements"] = deepcopy(replacements)
        self._parameters = parameters

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id or not self.project_id:
            raise RuntimeError(
                "Timeline repair command is not prepared"
            )
        artifact = uow.artifacts.get(self.artifact_id)
        current = artifact.get("current_version") or {}
        if current.get("id") != self.expected_current_version_id:
            raise ConflictError(
                "Timeline changed while Asset repair was running"
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
            note="替换缺失素材并重新编译时间线",
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
            "replacements": deepcopy(self.replacements),
            "repaired_version_id": self.expected_current_version_id,
            "asset_ids": asset_ids,
        }
        uow.artifact_graph.register_derivation(
            str(version["id"]),
            inputs,
            dependency_type="repaired_from",
            metadata=metadata,
            provenance={
                "prompt_version": "timeline-asset-repair@1",
                "parameters": {
                    "compile_parameters": deepcopy(self._parameters),
                    "asset_replacements": deepcopy(self.replacements),
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
                "asset_replacements": deepcopy(self.replacements),
            },
        )

        snapshot = _artifact_snapshot(saved)
        return OperationExecution(
            result={
                "timeline": timeline,
                "artifact": saved,
                "replacements": deepcopy(self.replacements),
            },
            audit_result={
                "artifact": snapshot,
                "version_id": version["id"],
                "replacements": deepcopy(self.replacements),
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
            "replacements": deepcopy(
                stored.get("replacements") or {}
            ),
        }


__all__ = ["RepairTimelineAssetsCommand"]
