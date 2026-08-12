"""Create a new regeneration Plan from the current graph of an old Plan."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.application.regeneration_plan_service import (
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.application.regeneration_replan_service import (
    normalized_replan_reason,
    validate_replan_source,
)
from app.store import UnitOfWork
from app.store.regeneration_replan_models import (
    RegenerationPlanReplanRow,
)
from app.store.repositories import ConflictError, new_id

from .base import OperationExecution


@dataclass(slots=True)
class ReplanRegenerationPlanCommand:
    source_plan_id: str
    expected_source_status: str
    expected_execution_attempt: int
    expected_snapshot_sha256: str
    reason: str = ""
    project_id: str | None = None

    operation_type = "regeneration.plan.replan"
    risk_level = "medium"
    target_type = "regeneration_plan"

    @property
    def target_id(self) -> str:
        return self.source_plan_id

    @property
    def idempotency_scope(self) -> str:
        return f"regeneration-plan:{self.source_plan_id}:replan"

    def arguments(self) -> dict[str, Any]:
        return {
            "source_plan_id": self.source_plan_id,
            "expected_source_status": self.expected_source_status,
            "expected_execution_attempt": (
                self.expected_execution_attempt
            ),
            "expected_snapshot_sha256": (
                self.expected_snapshot_sha256
            ),
            "reason": normalized_replan_reason(self.reason),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "regeneration_plan_status_is",
                "status": self.expected_source_status,
            },
            {
                "type": "regeneration_plan_execution_attempt_is",
                "attempt": self.expected_execution_attempt,
            },
            {"type": "regeneration_plan_has_no_active_work"},
            {"type": "regeneration_plan_has_no_replan_child"},
            {
                "type": "current_replan_snapshot_is",
                "sha256": self.expected_snapshot_sha256,
            },
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        source = validate_replan_source(
            uow,
            self.source_plan_id,
            expected_status=self.expected_source_status,
            expected_execution_attempt=(
                self.expected_execution_attempt
            ),
        )
        self.project_id = source["project_id"]

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        source = validate_replan_source(
            uow,
            self.source_plan_id,
            expected_status=self.expected_source_status,
            expected_execution_attempt=(
                self.expected_execution_attempt
            ),
        )
        preview = preview_regeneration_cascade(
            uow,
            source["project_id"],
            list(source["root_artifact_ids"]),
            include_downstream=bool(source["include_downstream"]),
        )
        actual_snapshot = regeneration_preview_snapshot_sha256(
            preview
        )
        if actual_snapshot != self.expected_snapshot_sha256:
            raise ConflictError(
                "regeneration graph changed before replan was committed"
            )

        target = uow.regeneration_plans.create_from_preview(
            preview,
            actual_snapshot,
        )
        relation = RegenerationPlanReplanRow(
            id=new_id(),
            project_id=source["project_id"],
            source_plan_id=self.source_plan_id,
            target_plan_id=target["id"],
            source_status=str(source["status"]),
            source_execution_attempt=int(
                source.get("execution_attempt") or 0
            ),
            target_snapshot_sha256=actual_snapshot,
            reason=normalized_replan_reason(self.reason),
            created_at=time.time(),
        )
        uow.session.add(relation)
        try:
            uow.session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "regeneration Plan already has a replan child"
            ) from exc

        return OperationExecution(
            result=target,
            audit_result={
                "source_plan_id": self.source_plan_id,
                "target_plan_id": target["id"],
                "relation_id": relation.id,
                "target_snapshot_sha256": actual_snapshot,
            },
            affected_entities=[
                {
                    "type": "regeneration_plan",
                    "id": self.source_plan_id,
                },
                {
                    "type": "regeneration_plan",
                    "id": target["id"],
                },
                *[
                    {
                        "type": "regeneration_plan_step",
                        "id": step["id"],
                    }
                    for step in target["steps"]
                ],
                {
                    "type": "regeneration_plan_replan",
                    "id": relation.id,
                },
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.regeneration_plans.get(
            str((audit_result or {})["target_plan_id"])
        )


__all__ = ["ReplanRegenerationPlanCommand"]
