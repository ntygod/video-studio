"""Semantic proposal commands."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.application.artifacts import accept_proposal, reject_proposal
from app.application.structure import ACTIONS
from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

from .base import CommandValidationError, OperationExecution


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


def _require_unit(
    uow: UnitOfWork,
    project_id: str,
    unit_id: str,
):
    unit = uow.units.get(unit_id)
    if unit.project_id != project_id:
        raise NotFoundError(unit_id)
    return unit


def _descendant_ids(
    uow: UnitOfWork,
    project_id: str,
    unit_id: str,
) -> set[str]:
    children_by_parent: dict[str, list[str]] = {}
    for unit in uow.units.list(project_id):
        if unit.parent_id:
            children_by_parent.setdefault(
                unit.parent_id,
                [],
            ).append(unit.id)
    result: set[str] = set()
    frontier = [unit_id]
    while frontier:
        for child_id in children_by_parent.get(
            frontier.pop(),
            [],
        ):
            if child_id in result:
                continue
            result.add(child_id)
            frontier.append(child_id)
    return result


@dataclass(slots=True)
class CreateArtifactChangeProposalCommand:
    project_id: str
    artifact_id: str
    operations: list[dict[str, Any]]
    title: str
    rationale: str = ""
    unit_id: str | None = None

    operation_type = "proposal.artifact_change.create"
    risk_level = "low"
    target_type = "artifact"

    @property
    def target_id(self) -> str:
        return self.artifact_id

    @property
    def idempotency_scope(self) -> str:
        return f"artifact:{self.artifact_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "unit_id": self.unit_id,
            "title": self.title,
            "rationale": self.rationale,
            "operation_count": len(self.operations),
            **_fingerprint(self.operations, "operations"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "artifact_belongs_to_project",
                "artifact_id": self.artifact_id,
                "project_id": self.project_id,
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        artifact = uow.artifacts.get(self.artifact_id)
        if artifact["project_id"] != self.project_id:
            raise NotFoundError(self.artifact_id)
        if self.unit_id:
            _require_unit(
                uow,
                self.project_id,
                self.unit_id,
            )
        if not str(self.title or "").strip():
            raise CommandValidationError(
                "proposal title cannot be empty"
            )
        if not self.operations:
            raise CommandValidationError(
                "proposal operations cannot be empty"
            )
        for index, operation in enumerate(self.operations):
            if not isinstance(operation, dict):
                raise CommandValidationError(
                    f"operations[{index}] must be an object"
                )
            op = str(operation.get("op") or "")
            path = str(operation.get("path") or "")
            if op not in {"add", "replace", "remove"}:
                raise CommandValidationError(
                    f"operations[{index}].op is invalid"
                )
            if not path.startswith("/"):
                raise CommandValidationError(
                    f"operations[{index}].path must start with /"
                )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        artifact = uow.artifacts.get(self.artifact_id)
        proposal = uow.proposals.create(
            {
                "project_id": self.project_id,
                "unit_id": self.unit_id
                or artifact.get("unit_id"),
                "artifact_id": self.artifact_id,
                "artifact_kind": artifact["kind"],
                "base_version_id": artifact.get(
                    "current_version_id"
                ),
                "title": self.title.strip(),
                "rationale": self.rationale,
                "operations": self.operations,
            }
        )
        return OperationExecution(
            result=proposal,
            audit_result={"proposal_id": proposal["id"]},
            affected_entities=[
                {"type": "proposal", "id": proposal["id"]}
            ],
            inverse_operation={
                "type": "proposal.reject_if_pending",
                "proposal_id": proposal["id"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.proposals.get(
            str((audit_result or {})["proposal_id"])
        )


@dataclass(slots=True)
class CreateStructureProposalCommand:
    project_id: str
    changes: list[dict[str, Any]]
    title: str
    rationale: str = ""
    unit_id: str | None = None

    operation_type = "proposal.structure.create"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "title": self.title,
            "rationale": self.rationale,
            "change_count": len(self.changes),
            **_fingerprint(self.changes, "changes"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "project_exists", "id": self.project_id}
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if self.unit_id:
            _require_unit(
                uow,
                self.project_id,
                self.unit_id,
            )
        if not str(self.title or "").strip():
            raise CommandValidationError(
                "proposal title cannot be empty"
            )
        if not self.changes:
            raise CommandValidationError(
                "structure changes cannot be empty"
            )

        descendants: dict[str, set[str]] = {}
        for index, change in enumerate(self.changes):
            if not isinstance(change, dict):
                raise CommandValidationError(
                    f"changes[{index}] must be an object"
                )
            action = str(change.get("action") or "")
            unit_id = str(change.get("unit_id") or "")
            if action not in ACTIONS:
                raise CommandValidationError(
                    f"changes[{index}].action is invalid"
                )
            if not unit_id:
                raise CommandValidationError(
                    f"changes[{index}].unit_id is required"
                )
            _require_unit(uow, self.project_id, unit_id)

            if action == "rename":
                if not str(
                    change.get("title") or ""
                ).strip():
                    raise CommandValidationError(
                        f"changes[{index}].title is required"
                    )
            elif action == "reorder":
                if change.get("order_index") is None:
                    raise CommandValidationError(
                        f"changes[{index}].order_index is required"
                    )
            elif action == "move":
                parent_id = change.get("parent_id") or None
                if not parent_id:
                    continue
                if parent_id == unit_id:
                    raise ConflictError(
                        "unit cannot be its own parent"
                    )
                _require_unit(
                    uow,
                    self.project_id,
                    str(parent_id),
                )
                descendants.setdefault(
                    unit_id,
                    _descendant_ids(
                        uow,
                        self.project_id,
                        unit_id,
                    ),
                )
                if parent_id in descendants[unit_id]:
                    raise ConflictError(
                        "unit cannot be moved inside its own subtree"
                    )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        proposal = uow.proposals.create(
            {
                "project_id": self.project_id,
                "unit_id": self.unit_id,
                "artifact_id": None,
                "artifact_kind": "structure",
                "base_version_id": None,
                "title": self.title.strip(),
                "rationale": self.rationale,
                "operations": self.changes,
            }
        )
        return OperationExecution(
            result=proposal,
            audit_result={"proposal_id": proposal["id"]},
            affected_entities=[
                {"type": "proposal", "id": proposal["id"]}
            ],
            inverse_operation={
                "type": "proposal.reject_if_pending",
                "proposal_id": proposal["id"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.proposals.get(
            str((audit_result or {})["proposal_id"])
        )


@dataclass(slots=True)
class AcceptProposalCommand:
    proposal_id: str
    op_indices: list[int] | None = None
    project_id: str | None = None

    operation_type = "proposal.accept"
    risk_level = "high"
    target_type = "proposal"

    @property
    def target_id(self) -> str:
        return self.proposal_id

    @property
    def idempotency_scope(self) -> str:
        return f"proposal:{self.proposal_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "op_indices": self.op_indices,
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "proposal_status_is",
                "status": "pending",
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        proposal = uow.proposals.get(self.proposal_id)
        self.project_id = proposal["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        result = accept_proposal(
            uow,
            self.proposal_id,
            op_indices=self.op_indices,
        )
        affected = [
            {"type": "proposal", "id": self.proposal_id}
        ]
        if result.get("artifact_id"):
            affected.append(
                {
                    "type": "artifact",
                    "id": result["artifact_id"],
                }
            )
        version = result.get("version") or {}
        if version.get("id"):
            affected.append(
                {
                    "type": "artifact_version",
                    "id": version["id"],
                }
            )
        for change in result.get("applied") or []:
            unit_id = change.get("unit_id")
            if unit_id:
                affected.append(
                    {"type": "unit", "id": unit_id}
                )
        return OperationExecution(
            result=result,
            audit_result={
                "proposal_id": self.proposal_id,
                "artifact_id": result.get("artifact_id"),
                "version_id": version.get("id"),
                "applied": result.get("applied") or [],
            },
            affected_entities=affected,
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        stored = audit_result or {}
        version_id = stored.get("version_id")
        return {
            "proposal": uow.proposals.get(self.proposal_id),
            "artifact_id": stored.get("artifact_id"),
            "version": (
                uow.artifacts.get_version(str(version_id))
                if version_id
                else None
            ),
            "applied": stored.get("applied") or [],
        }


@dataclass(slots=True)
class RejectProposalCommand:
    proposal_id: str
    project_id: str | None = None

    operation_type = "proposal.reject"
    risk_level = "medium"
    target_type = "proposal"

    @property
    def target_id(self) -> str:
        return self.proposal_id

    @property
    def idempotency_scope(self) -> str:
        return f"proposal:{self.proposal_id}"

    def arguments(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id}

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "proposal_status_is",
                "status": "pending",
            }
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        proposal = uow.proposals.get(self.proposal_id)
        self.project_id = proposal["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        result = reject_proposal(uow, self.proposal_id)
        return OperationExecution(
            result=result,
            audit_result={"proposal_id": self.proposal_id},
            affected_entities=[
                {"type": "proposal", "id": self.proposal_id}
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.proposals.get(self.proposal_id)
