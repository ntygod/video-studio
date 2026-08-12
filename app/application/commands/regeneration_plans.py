"""CommandBus operations for durable regeneration plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.application.regeneration_plan_service import (
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.store import UnitOfWork
from app.store.regeneration_repository import (
    TERMINAL_PLAN_STATUSES,
    TERMINAL_STEP_STATUSES,
)
from app.store.repositories import ConflictError, NotFoundError

from .base import CommandValidationError, OperationExecution
from .timeline_repair import RepairTimelineAssetsCommand


def _mapping_fingerprint(value: dict[str, str]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class CreateRegenerationPlanCommand:
    project_id: str
    artifact_ids: list[str]
    include_downstream: bool
    expected_snapshot_sha256: str

    operation_type = "regeneration.plan.create"
    risk_level = "medium"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:regeneration-plan"

    def arguments(self) -> dict[str, Any]:
        return {
            "artifact_ids": list(self.artifact_ids),
            "include_downstream": self.include_downstream,
            "expected_snapshot_sha256": (
                self.expected_snapshot_sha256
            ),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "project_exists", "id": self.project_id},
            {
                "type": "regeneration_preview_snapshot_is",
                "sha256": self.expected_snapshot_sha256,
            },
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not self.artifact_ids:
            raise CommandValidationError(
                "regeneration plan requires at least one Artifact"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        preview = preview_regeneration_cascade(
            uow,
            self.project_id,
            self.artifact_ids,
            include_downstream=self.include_downstream,
        )
        actual = regeneration_preview_snapshot_sha256(preview)
        if actual != self.expected_snapshot_sha256:
            raise ConflictError(
                "regeneration preview changed before the plan was created"
            )
        plan = uow.regeneration_plans.create_from_preview(
            preview,
            actual,
        )
        affected = [
            {"type": "regeneration_plan", "id": plan["id"]},
            *[
                {
                    "type": "regeneration_plan_step",
                    "id": step["id"],
                }
                for step in plan["steps"]
            ],
        ]
        return OperationExecution(
            result=plan,
            audit_result={"plan_id": plan["id"]},
            affected_entities=affected,
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.regeneration_plans.get(
            str((audit_result or {})["plan_id"])
        )


@dataclass(slots=True)
class StartRegenerationPlanCommand:
    plan_id: str
    expected_snapshot_sha256: str
    project_id: str | None = None

    operation_type = "regeneration.plan.start"
    risk_level = "high"
    target_type = "regeneration_plan"

    @property
    def target_id(self) -> str:
        return self.plan_id

    @property
    def idempotency_scope(self) -> str:
        return f"regeneration-plan:{self.plan_id}:start"

    def arguments(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "expected_snapshot_sha256": (
                self.expected_snapshot_sha256
            ),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "regeneration_plan_snapshot_is",
                "sha256": self.expected_snapshot_sha256,
            },
            {"type": "planned_target_versions_are_current"},
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        plan = uow.regeneration_plans.get(self.plan_id)
        self.project_id = plan["project_id"]
        if plan["snapshot_sha256"] != self.expected_snapshot_sha256:
            raise ConflictError(
                "regeneration plan snapshot does not match"
            )
        if plan["status"] in TERMINAL_PLAN_STATUSES:
            raise ConflictError(
                f"regeneration plan is already {plan['status']}"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        plan = uow.regeneration_plans.get(self.plan_id)
        if plan["snapshot_sha256"] != self.expected_snapshot_sha256:
            raise ConflictError(
                "regeneration plan snapshot changed"
            )
        for step in plan["steps"]:
            expected = step.get("expected_version_id")
            if not expected:
                continue
            try:
                artifact = uow.artifacts.get(step["artifact_id"])
            except NotFoundError as exc:
                raise ConflictError(
                    f"planned Artifact no longer exists: {step['artifact_id']}"
                ) from exc
            if artifact["project_id"] != plan["project_id"]:
                raise ConflictError(
                    "planned Artifact moved to another project"
                )
            if artifact.get("current_version_id") != expected:
                raise ConflictError(
                    "planned target version changed: "
                    + step["artifact_id"]
                )
        started = uow.regeneration_plans.set_plan_status(
            self.plan_id,
            "running",
        )
        return OperationExecution(
            result=uow.regeneration_plans.get(self.plan_id),
            audit_result={"plan_id": self.plan_id},
            affected_entities=[
                {"type": "regeneration_plan", "id": self.plan_id}
            ],
            inverse_operation={
                "type": "regeneration_plan.cancel",
                "plan_id": self.plan_id,
                "expected_status": started["status"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.regeneration_plans.get(
            str((audit_result or {})["plan_id"])
        )


@dataclass(slots=True)
class SetRegenerationPlanStepInputCommand:
    step_id: str
    replacements: dict[str, str]
    project_id: str | None = None

    operation_type = "regeneration.plan.step.input.set"
    risk_level = "medium"
    target_type = "regeneration_plan_step"

    @property
    def target_id(self) -> str:
        return self.step_id

    @property
    def idempotency_scope(self) -> str:
        return f"regeneration-step:{self.step_id}:input"

    def arguments(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "replacements": dict(sorted(self.replacements.items())),
            "replacements_sha256": _mapping_fingerprint(
                self.replacements
            ),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "regeneration_step_requires_input"},
            {"type": "replacement_assets_are_compatible"},
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        step = uow.regeneration_plans.get_step(self.step_id)
        plan = uow.regeneration_plans.get(step["plan_id"])
        self.project_id = plan["project_id"]
        if plan["status"] in TERMINAL_PLAN_STATUSES:
            raise ConflictError(
                f"regeneration plan is already {plan['status']}"
            )
        missing = set(step["direct_missing_asset_ids"])
        normalized = {
            str(source): str(target)
            for source, target in self.replacements.items()
            if str(source) and str(target)
        }
        if set(normalized) != missing:
            raise CommandValidationError(
                "replacement mapping must cover every direct missing Asset"
            )
        if len(set(normalized.values())) != len(normalized):
            raise CommandValidationError(
                "each missing Asset requires a distinct replacement"
            )
        self.replacements = normalized
        validator = RepairTimelineAssetsCommand(
            artifact_id=step["artifact_id"],
            replacements=normalized,
            expected_current_version_id=str(
                step["expected_version_id"] or ""
            ),
        )
        validator.prepare(uow)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        step = uow.regeneration_plans.get_step(self.step_id)
        status = (
            "waiting_for_predecessors"
            if step["depends_on_artifact_ids"]
            else "ready"
        )
        saved = uow.regeneration_plans.set_step_input(
            self.step_id,
            {"replacements": dict(self.replacements)},
            status=status,
        )
        plan = uow.regeneration_plans.get(saved["plan_id"])
        if plan["status"] == "blocked" and plan["started_at"]:
            uow.regeneration_plans.set_plan_status(
                plan["id"],
                "running",
            )
        return OperationExecution(
            result=saved,
            audit_result={"step_id": self.step_id},
            affected_entities=[
                {
                    "type": "regeneration_plan",
                    "id": saved["plan_id"],
                },
                {
                    "type": "regeneration_plan_step",
                    "id": self.step_id,
                },
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.regeneration_plans.get_step(
            str((audit_result or {})["step_id"])
        )


@dataclass(slots=True)
class CancelRegenerationPlanCommand:
    plan_id: str
    project_id: str | None = None

    operation_type = "regeneration.plan.cancel"
    risk_level = "high"
    target_type = "regeneration_plan"

    @property
    def target_id(self) -> str:
        return self.plan_id

    @property
    def idempotency_scope(self) -> str:
        return f"regeneration-plan:{self.plan_id}:cancel"

    def arguments(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id}

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "regeneration_plan_is_not_terminal"}]

    def prepare(self, uow: UnitOfWork) -> None:
        plan = uow.regeneration_plans.get(self.plan_id)
        self.project_id = plan["project_id"]
        if plan["status"] in TERMINAL_PLAN_STATUSES:
            raise ConflictError(
                f"regeneration plan is already {plan['status']}"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        plan = uow.regeneration_plans.get(self.plan_id)
        affected = [
            {"type": "regeneration_plan", "id": self.plan_id}
        ]
        for step in plan["steps"]:
            if step["status"] in TERMINAL_STEP_STATUSES:
                continue
            if step.get("job_id"):
                try:
                    uow.jobs.request_cancel(step["job_id"])
                except NotFoundError:
                    pass
            uow.regeneration_plans.set_step_status(
                step["id"],
                "canceled",
                error="regeneration plan canceled",
            )
            affected.append(
                {
                    "type": "regeneration_plan_step",
                    "id": step["id"],
                }
            )
        uow.regeneration_plans.set_plan_status(
            self.plan_id,
            "canceled",
        )
        return OperationExecution(
            result=uow.regeneration_plans.get(self.plan_id),
            audit_result={"plan_id": self.plan_id},
            affected_entities=affected,
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return uow.regeneration_plans.get(
            str((audit_result or {})["plan_id"])
        )


__all__ = [
    "CancelRegenerationPlanCommand",
    "CreateRegenerationPlanCommand",
    "SetRegenerationPlanStepInputCommand",
    "StartRegenerationPlanCommand",
]
