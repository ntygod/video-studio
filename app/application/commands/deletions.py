"""High-risk deletion commands with external-resource compensation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

from .base import OperationExecution
from .media_saga import quarantine_project_directory


def _subtree(
    uow: UnitOfWork,
    project_id: str,
    root_id: str,
) -> list[Any]:
    units = uow.units.list(project_id)
    by_parent: dict[str | None, list[Any]] = {}
    by_id = {unit.id: unit for unit in units}
    if root_id not in by_id:
        raise NotFoundError(root_id)
    for unit in units:
        by_parent.setdefault(unit.parent_id, []).append(unit)
    result: list[Any] = []
    frontier = [root_id]
    seen: set[str] = set()
    while frontier:
        unit_id = frontier.pop()
        if unit_id in seen:
            raise ConflictError("unit tree contains a cycle")
        seen.add(unit_id)
        unit = by_id[unit_id]
        result.append(unit)
        frontier.extend(
            child.id for child in by_parent.get(unit_id, [])
        )
    return result


def _unit_directory_files(
    media_store: Any,
    project_id: str,
    unit_ids: set[str],
) -> list[str]:
    root = media_store.root.resolve()
    project_dir = (root / project_id).resolve()
    if project_dir.parent != root or not project_dir.exists():
        return []
    result: list[str] = []
    for unit_id in unit_ids:
        directory = (project_dir / unit_id).resolve()
        if directory.parent != project_dir or not directory.exists():
            continue
        result.extend(
            path.relative_to(root).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        )
    return result


@dataclass(slots=True)
class DeleteProjectCommand:
    project_id: str
    media_store: Any = field(repr=False)
    expected_revision: int | None = None
    _operation_id: str | None = field(default=None, init=False, repr=False)
    _prepared_project: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _prepared_stats: dict[str, Any] | None = field(default=None, init=False, repr=False)

    operation_type = "project.delete"
    risk_level = "high"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:delete"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "expected_revision": self.expected_revision,
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {"type": "project_exists", "id": self.project_id}
        ]
        if self.expected_revision is not None:
            conditions.append(
                {
                    "type": "project_revision_is",
                    "revision": self.expected_revision,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        project = uow.projects.get(self.project_id)
        if self.expected_revision is not None and project.revision != self.expected_revision:
            raise ConflictError(
                "project changed after the delete operation was requested"
            )
        self._prepared_project = project.model_dump(mode="json")
        self._prepared_stats = uow.projects.stats(self.project_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id or self._prepared_project is None or self._prepared_stats is None:
            raise RuntimeError("delete project command is not prepared")
        current = uow.projects.get(self.project_id)
        if current.revision != self._prepared_project["revision"]:
            raise ConflictError(
                "project changed after the delete operation was prepared"
            )
        moved = quarantine_project_directory(
            self.media_store,
            self.project_id,
            self._operation_id,
        )
        try:
            uow.projects.delete(self.project_id)
        except Exception:
            self.media_store.restore_operation_quarantine(self._operation_id)
            raise
        result = {
            "ok": True,
            "project": deepcopy(self._prepared_project),
            "stats": deepcopy(self._prepared_stats),
            "quarantined_uris": moved,
        }
        return OperationExecution(
            result=result,
            audit_result=result,
            affected_entities=[{"type": "project", "id": self.project_id}],
            inverse_operation=None,
            on_rollback=lambda: self.media_store.restore_operation_quarantine(
                self._operation_id
            ),
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class DeleteUnitSubtreeCommand:
    project_id: str
    unit_id: str
    media_store: Any = field(repr=False)
    expected_updated_at: float | None = None
    _operation_id: str | None = field(default=None, init=False, repr=False)
    _prepared_units: list[dict[str, Any]] | None = field(default=None, init=False, repr=False)

    operation_type = "unit.delete"
    risk_level = "high"
    target_type = "unit"

    @property
    def target_id(self) -> str:
        return self.unit_id

    @property
    def idempotency_scope(self) -> str:
        return f"unit:{self.unit_id}:delete"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "unit_id": self.unit_id,
            "expected_updated_at": self.expected_updated_at,
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {
                "type": "unit_belongs_to_project",
                "unit_id": self.unit_id,
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
        uow.projects.get(self.project_id)
        root = uow.units.get(self.unit_id)
        if root.project_id != self.project_id:
            raise NotFoundError(self.unit_id)
        if (
            self.expected_updated_at is not None
            and root.updated_at != self.expected_updated_at
        ):
            raise ConflictError(
                "unit changed after the delete operation was requested"
            )
        self._prepared_units = [
            unit.model_dump(mode="json")
            for unit in _subtree(uow, self.project_id, self.unit_id)
        ]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id or self._prepared_units is None:
            raise RuntimeError("delete unit command is not prepared")
        current = [
            unit.model_dump(mode="json")
            for unit in _subtree(uow, self.project_id, self.unit_id)
        ]
        prepared_by_id = {
            item["id"]: item for item in self._prepared_units
        }
        current_by_id = {item["id"]: item for item in current}
        if set(prepared_by_id) != set(current_by_id):
            raise ConflictError(
                "unit subtree changed after deletion was prepared"
            )
        for unit_id, snapshot in prepared_by_id.items():
            if current_by_id[unit_id]["updated_at"] != snapshot["updated_at"]:
                raise ConflictError(
                    f"unit {unit_id} changed after deletion was prepared"
                )

        unit_ids = set(prepared_by_id)
        assets = [
            item
            for item in uow.assets.list(self.project_id)
            if item.get("unit_id") in unit_ids
        ]
        artifacts = [
            item
            for item in uow.artifacts.list(
                self.project_id,
                include_payload=False,
            )
            if item.get("unit_id") in unit_ids
        ]
        media_uris: list[str] = []
        for asset in assets:
            media_uris.extend(
                [
                    str(asset.get("uri") or ""),
                    str(asset.get("thumb_uri") or ""),
                ]
            )
        media_uris.extend(
            _unit_directory_files(
                self.media_store,
                self.project_id,
                unit_ids,
            )
        )
        moved = self.media_store.quarantine_asset(
            media_uris,
            self._operation_id,
        )
        try:
            uow.units.delete(self.unit_id)
            uow.session.flush()
        except Exception:
            self.media_store.restore_operation_quarantine(self._operation_id)
            raise

        result = {
            "ok": True,
            "root_unit_id": self.unit_id,
            "deleted_units": [
                {"id": item["id"], "title": item["title"]}
                for item in self._prepared_units
            ],
            "deleted_asset_ids": [item["id"] for item in assets],
            "deleted_artifact_ids": [item["id"] for item in artifacts],
            "quarantined_uris": moved,
        }
        affected = [
            *[
                {"type": "unit", "id": item["id"]}
                for item in self._prepared_units
            ],
            *[
                {"type": "asset", "id": item["id"]}
                for item in assets
            ],
            *[
                {"type": "artifact", "id": item["id"]}
                for item in artifacts
            ],
        ]
        return OperationExecution(
            result=result,
            audit_result=result,
            affected_entities=affected,
            inverse_operation=None,
            on_rollback=lambda: self.media_store.restore_operation_quarantine(
                self._operation_id
            ),
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        return deepcopy(audit_result)


__all__ = ["DeleteProjectCommand", "DeleteUnitSubtreeCommand"]
