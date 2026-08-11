"""High-risk deletion commands with external-resource compensation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import ConflictError

from .base import OperationExecution
from .media_saga import quarantine_project_directory


@dataclass(slots=True)
class DeleteProjectCommand:
    project_id: str
    media_store: Any = field(repr=False)
    expected_revision: int | None = None
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _prepared_project: dict[str, Any] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _prepared_stats: dict[str, Any] | None = field(
        default=None,
        init=False,
        repr=False,
    )

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
        if (
            self.expected_revision is not None
            and project.revision != self.expected_revision
        ):
            raise ConflictError(
                "project changed after the delete operation was requested"
            )
        self._prepared_project = project.model_dump(mode="json")
        self._prepared_stats = uow.projects.stats(self.project_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if (
            not self._operation_id
            or self._prepared_project is None
            or self._prepared_stats is None
        ):
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
            self.media_store.restore_operation_quarantine(
                self._operation_id
            )
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
            affected_entities=[
                {"type": "project", "id": self.project_id}
            ],
            # Restoring a cascaded project requires complete relational
            # snapshots, so the quarantine is retained without advertising an
            # unsafe one-click inverse.
            inverse_operation=None,
            on_rollback=(
                lambda operation_id=self._operation_id:
                self.media_store.restore_operation_quarantine(
                    operation_id
                )
            ),
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


__all__ = ["DeleteProjectCommand"]
