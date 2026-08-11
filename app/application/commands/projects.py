"""Semantic project and creative-unit commands."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.application.projects import (
    create_project,
    create_units,
    patch_project,
)
from app.domain import CreativeUnit
from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

from .base import CommandValidationError, OperationExecution

PROJECT_PATCH_FIELDS = frozenset(
    {
        "title",
        "project_type",
        "workflow_id",
        "stage",
        "brief",
        "bible",
        "settings",
        "custom_fields",
    }
)
UNIT_PATCH_FIELDS = frozenset(
    {
        "parent_id",
        "unit_type",
        "order_index",
        "title",
        "summary",
        "stage",
        "continuity_summary",
        "custom_fields",
    }
)
MAX_UNIT_BATCH = 500


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


def _project_json(project) -> dict[str, Any]:
    return project.model_dump(mode="json")


def _unit_json(unit) -> dict[str, Any]:
    return unit.model_dump(mode="json")


def _validate_patch(
    patch: dict[str, Any],
    allowed: frozenset[str],
    target: str,
) -> None:
    if not patch:
        raise CommandValidationError(
            f"{target} patch cannot be empty"
        )
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise CommandValidationError(
            f"unsupported {target} patch fields: "
            + ", ".join(unknown)
        )


def _validate_parent_change(
    uow: UnitOfWork,
    project_id: str,
    unit_id: str,
    parent_id: str | None,
) -> None:
    if not parent_id:
        return
    if parent_id == unit_id:
        raise ConflictError("unit cannot be its own parent")
    parent = uow.units.get(parent_id)
    if parent.project_id != project_id:
        raise NotFoundError(parent_id)

    children_by_parent: dict[str, list[str]] = {}
    for candidate in uow.units.list(project_id):
        if candidate.parent_id:
            children_by_parent.setdefault(
                candidate.parent_id,
                [],
            ).append(candidate.id)
    frontier = [unit_id]
    descendants: set[str] = set()
    while frontier:
        for child_id in children_by_parent.get(
            frontier.pop(),
            [],
        ):
            if child_id in descendants:
                continue
            descendants.add(child_id)
            frontier.append(child_id)
    if parent_id in descendants:
        raise ConflictError(
            "unit cannot be moved inside its own subtree"
        )


@dataclass(slots=True)
class CreateProjectCommand:
    title: str
    project_type: str = "freeform"
    workflow_id: str = "freeform"
    concept: str = ""
    format_id: str = "freeform"
    custom_fields: dict[str, Any] = field(default_factory=dict)
    project_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    operation_type = "project.create"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return "project:create"

    def arguments(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "project_type": self.project_type,
            "workflow_id": self.workflow_id,
            "concept": self.concept,
            "format_id": self.format_id,
            **_fingerprint(self.custom_fields, "custom_fields"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return []

    def prepare(self, uow: UnitOfWork) -> None:
        return None

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        project = create_project(
            uow,
            project_id=self.project_id,
            title=self.title,
            project_type=self.project_type,
            workflow_id=self.workflow_id,
            concept=self.concept,
            format_id=self.format_id,
            custom_fields=self.custom_fields,
        )
        artifacts = uow.artifacts.list(
            project.id,
            unit_id=None,
            include_payload=False,
        )
        affected = [{"type": "project", "id": project.id}]
        for artifact in artifacts:
            affected.append(
                {"type": "artifact", "id": artifact["id"]}
            )
            version = artifact.get("current_version") or {}
            if version.get("id"):
                affected.append(
                    {
                        "type": "artifact_version",
                        "id": version["id"],
                    }
                )
        snapshot = _project_json(project)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=affected,
            inverse_operation={
                "type": "project.delete_if_empty",
                "project_id": project.id,
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class PatchProjectCommand:
    project_id: str
    patch: dict[str, Any]
    expected_revision: int

    operation_type = "project.patch"
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
            "expected_revision": self.expected_revision,
            "patch_keys": sorted(self.patch),
            **_fingerprint(self.patch, "patch"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "project_revision_is",
                "revision": self.expected_revision,
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        _validate_patch(
            self.patch,
            PROJECT_PATCH_FIELDS,
            "project",
        )
        if (
            "title" in self.patch
            and not str(self.patch.get("title") or "").strip()
        ):
            raise CommandValidationError(
                "project title cannot be empty"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        before = uow.projects.get(self.project_id)
        before_artifacts = {
            item["kind"]: (
                (item.get("current_version") or {}).get("id")
            )
            for item in uow.artifacts.list(
                self.project_id,
                unit_id=None,
                include_payload=False,
            )
            if item["kind"] in {"brief", "project_bible"}
        }
        saved = patch_project(
            uow,
            self.project_id,
            self.patch,
            self.expected_revision,
        )
        after_artifacts = uow.artifacts.list(
            self.project_id,
            unit_id=None,
            include_payload=False,
        )
        affected = [
            {"type": "project", "id": self.project_id}
        ]
        for artifact in after_artifacts:
            if artifact["kind"] not in {
                "brief",
                "project_bible",
            }:
                continue
            version_id = (
                (artifact.get("current_version") or {}).get("id")
            )
            if before_artifacts.get(artifact["kind"]) == version_id:
                continue
            affected.append(
                {"type": "artifact", "id": artifact["id"]}
            )
            if version_id:
                affected.append(
                    {
                        "type": "artifact_version",
                        "id": version_id,
                    }
                )
        snapshot = _project_json(saved)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=affected,
            inverse_operation={
                "type": "project.restore_snapshot",
                "project": _project_json(before),
                "expected_revision": saved.revision,
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class CreateUnitsCommand:
    project_id: str
    definitions: list[dict[str, Any]]
    _prepared_definitions: list[dict[str, Any]] = field(
        init=False,
        repr=False,
    )
    _input_ids: list[str] = field(
        init=False,
        repr=False,
    )

    operation_type = "unit.create_many"
    risk_level = "low"
    target_type = "project"

    def __post_init__(self) -> None:
        source = deepcopy(self.definitions)
        self.definitions = source
        self._prepared_definitions = []
        self._input_ids = []
        for definition in source:
            prepared = deepcopy(definition)
            unit_id = prepared.get("id") or uuid.uuid4().hex
            prepared["id"] = unit_id
            self._prepared_definitions.append(prepared)
            self._input_ids.append(unit_id)

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "count": len(self.definitions),
            **_fingerprint(self.definitions, "definitions"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "project_exists", "id": self.project_id}]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        count = len(self._prepared_definitions)
        if count < 1:
            raise CommandValidationError(
                "unit batch cannot be empty"
            )
        if count > MAX_UNIT_BATCH:
            raise CommandValidationError(
                f"unit batch cannot exceed {MAX_UNIT_BATCH}"
            )

        by_id: dict[str, dict[str, Any]] = {}
        for definition in self._prepared_definitions:
            unit_id = str(definition["id"])
            if unit_id in by_id:
                raise CommandValidationError(
                    f"duplicate unit id: {unit_id}"
                )
            if not str(
                definition.get("title") or ""
            ).strip():
                raise CommandValidationError(
                    f"unit title cannot be empty: {unit_id}"
                )
            by_id[unit_id] = definition

        for unit_id, definition in by_id.items():
            parent_id = definition.get("parent_id") or None
            if not parent_id:
                continue
            if parent_id == unit_id:
                raise ConflictError(
                    "unit cannot be its own parent"
                )
            if parent_id in by_id:
                continue
            parent = uow.units.get(parent_id)
            if parent.project_id != self.project_id:
                raise NotFoundError(parent_id)

        ordered: list[dict[str, Any]] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(unit_id: str) -> None:
            if unit_id in visited:
                return
            if unit_id in visiting:
                raise ConflictError(
                    "unit batch contains a parent cycle"
                )
            visiting.add(unit_id)
            definition = by_id[unit_id]
            parent_id = definition.get("parent_id") or None
            if parent_id in by_id:
                visit(str(parent_id))
            visiting.remove(unit_id)
            visited.add(unit_id)
            ordered.append(definition)

        for unit_id in self._input_ids:
            visit(unit_id)
        self._prepared_definitions = ordered

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        units = create_units(
            uow,
            self.project_id,
            self._prepared_definitions,
        )
        by_id = {unit.id: unit for unit in units}
        snapshots = [
            _unit_json(by_id[unit_id])
            for unit_id in self._input_ids
        ]
        return OperationExecution(
            result=snapshots,
            audit_result=snapshots,
            affected_entities=[
                {"type": "unit", "id": unit_id}
                for unit_id in self._input_ids
            ],
            inverse_operation={
                "type": "unit.delete_many_if_pristine",
                "unit_ids": self._input_ids,
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> list[dict[str, Any]]:
        return deepcopy(audit_result or [])


@dataclass(slots=True)
class PatchUnitCommand:
    project_id: str
    unit_id: str
    patch: dict[str, Any]
    expected_updated_at: float | None = None

    operation_type = "unit.patch"
    risk_level = "medium"
    target_type = "unit"

    @property
    def target_id(self) -> str:
        return self.unit_id

    @property
    def idempotency_scope(self) -> str:
        return f"unit:{self.unit_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "expected_updated_at": self.expected_updated_at,
            "patch_keys": sorted(self.patch),
            **_fingerprint(self.patch, "patch"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions = [
            {
                "type": "unit_belongs_to_project",
                "project_id": self.project_id,
            }
        ]
        if self.expected_updated_at is not None:
            conditions.append(
                {
                    "type": "unit_updated_at_is",
                    "updated_at": self.expected_updated_at,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        unit = uow.units.get(self.unit_id)
        if unit.project_id != self.project_id:
            raise NotFoundError(self.unit_id)
        _validate_patch(
            self.patch,
            UNIT_PATCH_FIELDS,
            "unit",
        )
        if (
            "title" in self.patch
            and not str(self.patch.get("title") or "").strip()
        ):
            raise CommandValidationError(
                "unit title cannot be empty"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        unit = uow.units.get(self.unit_id)
        if unit.project_id != self.project_id:
            raise NotFoundError(self.unit_id)
        if (
            self.expected_updated_at is not None
            and abs(
                unit.updated_at - self.expected_updated_at
            )
            > 0.000001
        ):
            raise ConflictError(
                "unit changed after it was loaded"
            )
        if "parent_id" in self.patch:
            _validate_parent_change(
                uow,
                self.project_id,
                self.unit_id,
                self.patch.get("parent_id") or None,
            )

        before = _unit_json(unit)
        data = deepcopy(before)
        for key, value in self.patch.items():
            data[key] = value
        saved = uow.units.update(
            CreativeUnit.model_validate(data)
        )
        snapshot = _unit_json(saved)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "unit", "id": self.unit_id}
            ],
            inverse_operation={
                "type": "unit.restore_snapshot",
                "unit": before,
                "expected_updated_at": saved.updated_at,
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)
