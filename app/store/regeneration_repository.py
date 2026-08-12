"""Repository for durable selective-regeneration plans."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from .json_codec import dumps, loads
from .regeneration_models import (
    RegenerationPlanRow,
    RegenerationPlanStepRow,
)
from .repositories import ConflictError, NotFoundError, new_id

PLAN_STATUSES = frozenset(
    {
        "draft",
        "running",
        "blocked",
        "succeeded",
        "failed",
        "canceled",
    }
)
STEP_STATUSES = frozenset(
    {
        "ready",
        "waiting_for_predecessors",
        "requires_input",
        "requires_review",
        "manual",
        "blocked",
        "skipped",
        "queued",
        "running",
        "succeeded",
        "failed",
        "canceled",
    }
)
TERMINAL_PLAN_STATUSES = frozenset(
    {"succeeded", "failed", "canceled"}
)
TERMINAL_STEP_STATUSES = frozenset(
    {"skipped", "succeeded", "failed", "canceled"}
)


class RegenerationPlanRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _step(row: RegenerationPlanStepRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "project_id": row.project_id,
            "artifact_id": row.artifact_id,
            "order_index": row.order_index,
            "artifact_kind": row.artifact_kind,
            "artifact_name": row.artifact_name,
            "unit_id": row.unit_id,
            "expected_version_id": row.expected_version_id,
            "action": row.action,
            "status": row.status,
            "can_execute_automatically": row.can_execute_automatically,
            "depends_on_artifact_ids": loads(
                row.depends_on_artifact_ids_json, []
            ),
            "external_upstream_artifact_ids": loads(
                row.external_upstream_artifact_ids_json, []
            ),
            "blockers": loads(row.blockers_json, []),
            "missing_asset_ids": loads(row.missing_asset_ids_json, []),
            "direct_missing_asset_ids": loads(
                row.direct_missing_asset_ids_json, []
            ),
            "source_job_id": row.source_job_id,
            "job_id": row.job_id,
            "input": loads(row.input_json, {}),
            "result": loads(row.result_json, {}),
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }

    @classmethod
    def _plan(cls, row, steps=None) -> dict[str, Any]:
        result = {
            "id": row.id,
            "project_id": row.project_id,
            "status": row.status,
            "root_artifact_ids": loads(row.root_artifact_ids_json, []),
            "include_downstream": row.include_downstream,
            "snapshot_sha256": row.snapshot_sha256,
            "summary": loads(row.summary_json, {}),
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
        if steps is not None:
            result["steps"] = [cls._step(step) for step in steps]
        return result

    def _plan_row(self, plan_id):
        row = self.session.get(RegenerationPlanRow, plan_id)
        if row is None:
            raise NotFoundError(plan_id)
        return row

    def _step_row(self, step_id):
        row = self.session.get(RegenerationPlanStepRow, step_id)
        if row is None:
            raise NotFoundError(step_id)
        return row

    def _step_rows(self, plan_id):
        return self.session.scalars(
            select(RegenerationPlanStepRow)
            .where(RegenerationPlanStepRow.plan_id == plan_id)
            .order_by(
                RegenerationPlanStepRow.order_index,
                RegenerationPlanStepRow.id,
            )
        ).all()

    def steps(self, plan_id):
        self._plan_row(plan_id)
        return [self._step(row) for row in self._step_rows(plan_id)]

    def get(self, plan_id):
        row = self._plan_row(plan_id)
        return self._plan(row, self._step_rows(plan_id))

    def get_step(self, step_id):
        return self._step(self._step_row(step_id))

    def find_step_by_job(self, job_id):
        row = self.session.scalar(
            select(RegenerationPlanStepRow).where(
                RegenerationPlanStepRow.job_id == job_id
            )
        )
        return self._step(row) if row else None

    def create_from_preview(self, preview, snapshot_sha256):
        now = time.time()
        plan = RegenerationPlanRow(
            id=new_id(),
            project_id=str(preview["project_id"]),
            status="draft",
            root_artifact_ids_json=dumps(
                preview.get("root_artifact_ids") or []
            ),
            include_downstream=bool(
                preview.get("include_downstream", True)
            ),
            snapshot_sha256=snapshot_sha256,
            summary_json=dumps(preview.get("summary") or {}),
            error="",
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        self.session.add(plan)
        self.session.flush()
        for order_index, item in enumerate(preview.get("steps") or []):
            status = str(item.get("execution_state") or "blocked")
            if status not in STEP_STATUSES:
                raise ConflictError(
                    f"unsupported regeneration step state: {status}"
                )
            self.session.add(
                RegenerationPlanStepRow(
                    id=new_id(),
                    plan_id=plan.id,
                    project_id=plan.project_id,
                    artifact_id=str(item["artifact_id"]),
                    order_index=order_index,
                    artifact_kind=str(item.get("artifact_kind") or ""),
                    artifact_name=str(item.get("artifact_name") or ""),
                    unit_id=(str(item["unit_id"]) if item.get("unit_id") else None),
                    expected_version_id=(
                        str(item["expected_current_version_id"])
                        if item.get("expected_current_version_id") else None
                    ),
                    action=str(item.get("action") or "manual"),
                    status=status,
                    can_execute_automatically=bool(
                        item.get("can_execute_automatically")
                    ),
                    depends_on_artifact_ids_json=dumps(
                        item.get("depends_on") or []
                    ),
                    external_upstream_artifact_ids_json=dumps(
                        item.get("external_upstream_artifact_ids") or []
                    ),
                    blockers_json=dumps(item.get("blockers") or []),
                    missing_asset_ids_json=dumps(
                        item.get("missing_asset_ids") or []
                    ),
                    direct_missing_asset_ids_json=dumps(
                        item.get("direct_missing_asset_ids") or []
                    ),
                    source_job_id=(
                        str(item["source_job_id"])
                        if item.get("source_job_id") else None
                    ),
                    job_id=None,
                    input_json="{}",
                    result_json="{}",
                    error="",
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=(now if status == "skipped" else None),
                )
            )
        self.session.flush()
        return self.get(plan.id)

    def list(self, project_id, *, limit=100):
        limit = max(1, min(int(limit), 200))
        rows = self.session.scalars(
            select(RegenerationPlanRow)
            .where(RegenerationPlanRow.project_id == project_id)
            .order_by(
                RegenerationPlanRow.created_at.desc(),
                RegenerationPlanRow.id.desc(),
            )
            .limit(limit)
        ).all()
        return [self._plan(row) for row in rows]

    def active_ids(self):
        return list(
            self.session.scalars(
                select(RegenerationPlanRow.id)
                .where(RegenerationPlanRow.status == "running")
                .order_by(RegenerationPlanRow.updated_at)
            ).all()
        )

    def set_plan_status(self, plan_id, status, *, error=""):
        if status not in PLAN_STATUSES:
            raise ValueError(f"invalid regeneration plan status: {status}")
        row = self._plan_row(plan_id)
        now = time.time()
        row.status = status
        row.error = error
        row.updated_at = now
        if status == "running" and row.started_at is None:
            row.started_at = now
        if status in TERMINAL_PLAN_STATUSES:
            row.completed_at = now
        elif status in {"draft", "running", "blocked"}:
            row.completed_at = None
        self.session.flush()
        return self._plan(row)

    def update_summary(self, plan_id, summary):
        row = self._plan_row(plan_id)
        row.summary_json = dumps(deepcopy(summary))
        row.updated_at = time.time()
        self.session.flush()
        return self._plan(row)

    def set_step_status(
        self,
        step_id,
        status,
        *,
        job_id=None,
        result=None,
        error="",
        blockers=None,
    ):
        if status not in STEP_STATUSES:
            raise ValueError(f"invalid regeneration step status: {status}")
        row = self._step_row(step_id)
        now = time.time()
        row.status = status
        if job_id is not None:
            row.job_id = job_id
        if result is not None:
            row.result_json = dumps(deepcopy(result))
        if blockers is not None:
            row.blockers_json = dumps(deepcopy(blockers))
        row.error = error
        row.updated_at = now
        if status in {"queued", "running"} and row.started_at is None:
            row.started_at = now
        if status in TERMINAL_STEP_STATUSES:
            row.completed_at = now
        else:
            row.completed_at = None
        self.session.flush()
        return self._step(row)

    def set_step_input(self, step_id, value, *, status):
        if status not in {"ready", "waiting_for_predecessors"}:
            raise ValueError("step input can only release a waiting step")
        row = self._step_row(step_id)
        if row.action != "repair_timeline_assets":
            raise ConflictError(
                "structured input is not supported for this step"
            )
        if row.status not in {"requires_input", "blocked"}:
            raise ConflictError(
                "step is not waiting for structured input"
            )
        row.input_json = dumps(deepcopy(value))
        row.status = status
        row.blockers_json = "[]"
        row.error = ""
        row.updated_at = time.time()
        row.completed_at = None
        self.session.flush()
        return self._step(row)


__all__ = [
    "PLAN_STATUSES",
    "STEP_STATUSES",
    "TERMINAL_PLAN_STATUSES",
    "TERMINAL_STEP_STATUSES",
    "RegenerationPlanRepository",
]
