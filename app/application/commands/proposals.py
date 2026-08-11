"""Semantic proposal review commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.artifacts import accept_proposal, reject_proposal
from app.store import UnitOfWork

from .base import OperationExecution


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
        return {"proposal_id": self.proposal_id, "op_indices": self.op_indices}

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "proposal_status_is", "status": "pending"}]

    def prepare(self, uow: UnitOfWork) -> None:
        proposal = uow.proposals.get(self.proposal_id)
        self.project_id = proposal["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        result = accept_proposal(uow, self.proposal_id, op_indices=self.op_indices)
        affected = [{"type": "proposal", "id": self.proposal_id}]
        if result.get("artifact_id"):
            affected.append({"type": "artifact", "id": result["artifact_id"]})
        version = result.get("version") or {}
        if version.get("id"):
            affected.append({"type": "artifact_version", "id": version["id"]})
        for change in result.get("applied") or []:
            unit_id = change.get("unit_id")
            if unit_id:
                affected.append({"type": "unit", "id": unit_id})
        return OperationExecution(
            result=result,
            audit_result={"proposal_id": self.proposal_id, "artifact_id": result.get("artifact_id"), "version_id": version.get("id"), "applied": result.get("applied") or []},
            affected_entities=affected,
            inverse_operation=None,
        )

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        stored = audit_result or {}
        version_id = stored.get("version_id")
        return {"proposal": uow.proposals.get(self.proposal_id), "artifact_id": stored.get("artifact_id"), "version": uow.artifacts.get_version(str(version_id)) if version_id else None, "applied": stored.get("applied") or []}


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
        return [{"type": "proposal_status_is", "status": "pending"}]

    def prepare(self, uow: UnitOfWork) -> None:
        proposal = uow.proposals.get(self.proposal_id)
        self.project_id = proposal["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        result = reject_proposal(uow, self.proposal_id)
        return OperationExecution(result=result, audit_result={"proposal_id": self.proposal_id}, affected_entities=[{"type": "proposal", "id": self.proposal_id}], inverse_operation=None)

    def replay(self, uow: UnitOfWork, audit_result: Any) -> dict[str, Any]:
        return uow.proposals.get(self.proposal_id)
