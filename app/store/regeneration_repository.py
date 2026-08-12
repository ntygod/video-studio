"""Repository for durable selective-regeneration plans."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy import func, or_, select, update

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
NONTERMINAL_PLAN_STATUSES = PLAN_STATUSES - TERMINAL_PLAN_STATUSES
NONTERMINAL_STEP_STATUSES = STEP_STATUSES - TERMINAL_STEP_STATUSES
CLAIMABLE_STEP_STATUSES = frozenset(
    {"ready", "waiting_for_predecessors"}
)


def _normalized_statuses(
    values: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    normalized = tuple(dict.fromkeys(str(value) for value in values))
    return normalized or tuple()


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
            "claimed": bool(row.claim_token),
            "claim_owner": row.claim_owner,
            "claim_until": row.claim_until,
            "claim_attempt": row.claim_attempt,
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
                    unit_id=(
                        str(item["unit_id"])
                        if item.get("unit_id")
                        else None
                    ),
                    expected_version_id=(
                        str(item["expected_current_version_id"])
                        if item.get("expected_current_version_id")
                        else None
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
                        if item.get("source_job_id")
                        else None
                    ),
                    job_id=None,
                    claim_token="",
                    claim_owner="",
                    claim_until=None,
                    claim_attempt=0,
                    input_json="{}",
                    result_json="{}",
                    error="",
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=(
                        now if status == "skipped" else None
                    ),
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

    def set_plan_status(
        self,
        plan_id,
        status,
        *,
        error="",
        expected_statuses: Iterable[str] | None = None,
    ):
        if status not in PLAN_STATUSES:
            raise ValueError(
                f"invalid regeneration plan status: {status}"
            )
        self._plan_row(plan_id)
        now = time.time()
        values: dict[str, Any] = {
            "status": status,
            "error": error,
            "updated_at": now,
            "completed_at": (
                now if status in TERMINAL_PLAN_STATUSES else None
            ),
        }
        if status == "running":
            values["started_at"] = func.coalesce(
                RegenerationPlanRow.started_at,
                now,
            )

        statement = update(RegenerationPlanRow).where(
            RegenerationPlanRow.id == plan_id
        )
        expected = _normalized_statuses(expected_statuses)
        if expected is not None:
            statement = statement.where(
                RegenerationPlanRow.status.in_(expected)
            )
        changed = self.session.execute(
            statement.values(**values).execution_options(
                synchronize_session=False
            )
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return self._plan(self._plan_row(plan_id))
        return self._plan(self._plan_row(plan_id))

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
        expected_statuses: Iterable[str] | None = None,
        clear_claim: bool = True,
    ):
        if status not in STEP_STATUSES:
            raise ValueError(
                f"invalid regeneration step status: {status}"
            )
        self._step_row(step_id)
        now = time.time()
        values: dict[str, Any] = {
            "status": status,
            "error": error,
            "updated_at": now,
            "completed_at": (
                now if status in TERMINAL_STEP_STATUSES else None
            ),
        }
        if status in {"queued", "running"}:
            values["started_at"] = func.coalesce(
                RegenerationPlanStepRow.started_at,
                now,
            )
        if job_id is not None:
            values["job_id"] = job_id
        if result is not None:
            values["result_json"] = dumps(deepcopy(result))
        if blockers is not None:
            values["blockers_json"] = dumps(deepcopy(blockers))
        if clear_claim:
            values.update(
                {
                    "claim_token": "",
                    "claim_owner": "",
                    "claim_until": None,
                }
            )

        statement = update(RegenerationPlanStepRow).where(
            RegenerationPlanStepRow.id == step_id
        )
        expected = _normalized_statuses(expected_statuses)
        if expected is not None:
            statement = statement.where(
                RegenerationPlanStepRow.status.in_(expected)
            )
        changed = self.session.execute(
            statement.values(**values).execution_options(
                synchronize_session=False
            )
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return self.get_step(step_id)
        return self.get_step(step_id)

    def claim_step(
        self,
        step_id: str,
        *,
        owner: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically lease one executable Step across app processes."""

        self._step_row(step_id)
        claimed_at = time.time() if now is None else float(now)
        lease = max(1.0, float(lease_seconds))
        token = new_id()
        normalized_owner = str(owner or "coordinator")[:160]
        running_plan_ids = select(RegenerationPlanRow.id).where(
            RegenerationPlanRow.status == "running"
        )
        changed = self.session.execute(
            update(RegenerationPlanStepRow)
            .where(
                RegenerationPlanStepRow.id == step_id,
                RegenerationPlanStepRow.status.in_(
                    tuple(CLAIMABLE_STEP_STATUSES)
                ),
                or_(
                    RegenerationPlanStepRow.claim_until.is_(None),
                    RegenerationPlanStepRow.claim_until <= claimed_at,
                ),
                RegenerationPlanStepRow.plan_id.in_(
                    running_plan_ids
                ),
            )
            .values(
                claim_token=token,
                claim_owner=normalized_owner,
                claim_until=claimed_at + lease,
                claim_attempt=(
                    RegenerationPlanStepRow.claim_attempt + 1
                ),
                started_at=func.coalesce(
                    RegenerationPlanStepRow.started_at,
                    claimed_at,
                ),
                updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return None
        step = self.get_step(step_id)
        step["_claim_token"] = token
        return step

    def owns_step_claim(
        self,
        step_id: str,
        claim_token: str,
    ) -> bool:
        return bool(
            self.session.scalar(
                select(RegenerationPlanStepRow.id).where(
                    RegenerationPlanStepRow.id == step_id,
                    RegenerationPlanStepRow.claim_token == claim_token,
                )
            )
        )

    def renew_step_claim(
        self,
        step_id: str,
        claim_token: str,
        *,
        lease_seconds: float,
        now: float | None = None,
    ) -> bool:
        renewed_at = time.time() if now is None else float(now)
        changed = self.session.execute(
            update(RegenerationPlanStepRow)
            .where(
                RegenerationPlanStepRow.id == step_id,
                RegenerationPlanStepRow.claim_token == claim_token,
            )
            .values(
                claim_until=renewed_at
                + max(1.0, float(lease_seconds)),
                updated_at=renewed_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        return changed.rowcount == 1

    def release_step_claim(
        self,
        step_id: str,
        claim_token: str,
    ) -> bool:
        changed = self.session.execute(
            update(RegenerationPlanStepRow)
            .where(
                RegenerationPlanStepRow.id == step_id,
                RegenerationPlanStepRow.claim_token == claim_token,
            )
            .values(
                claim_token="",
                claim_owner="",
                claim_until=None,
                updated_at=time.time(),
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        return changed.rowcount == 1

    def complete_step_claim(
        self,
        step_id: str,
        claim_token: str,
        status: str,
        *,
        job_id=None,
        result=None,
        error="",
        blockers=None,
    ) -> dict[str, Any] | None:
        """Finish a claimed dispatch only if this token still owns it."""

        if status not in STEP_STATUSES:
            raise ValueError(
                f"invalid regeneration step status: {status}"
            )
        now = time.time()
        values: dict[str, Any] = {
            "status": status,
            "error": error,
            "updated_at": now,
            "completed_at": (
                now if status in TERMINAL_STEP_STATUSES else None
            ),
            "claim_token": "",
            "claim_owner": "",
            "claim_until": None,
        }
        if status in {"queued", "running"}:
            values["started_at"] = func.coalesce(
                RegenerationPlanStepRow.started_at,
                now,
            )
        if job_id is not None:
            values["job_id"] = job_id
        if result is not None:
            values["result_json"] = dumps(deepcopy(result))
        if blockers is not None:
            values["blockers_json"] = dumps(deepcopy(blockers))

        changed = self.session.execute(
            update(RegenerationPlanStepRow)
            .where(
                RegenerationPlanStepRow.id == step_id,
                RegenerationPlanStepRow.claim_token == claim_token,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return None
        return self.get_step(step_id)

    def set_step_input(self, step_id, value, *, status):
        if status not in {"ready", "waiting_for_predecessors"}:
            raise ValueError(
                "step input can only release a waiting step"
            )
        row = self._step_row(step_id)
        if row.action != "repair_timeline_assets":
            raise ConflictError(
                "structured input is not supported for this step"
            )
        now = time.time()
        nonterminal_plan_ids = select(RegenerationPlanRow.id).where(
            RegenerationPlanRow.status.in_(
                tuple(NONTERMINAL_PLAN_STATUSES)
            )
        )
        changed = self.session.execute(
            update(RegenerationPlanStepRow)
            .where(
                RegenerationPlanStepRow.id == step_id,
                RegenerationPlanStepRow.action
                == "repair_timeline_assets",
                RegenerationPlanStepRow.status.in_(
                    ("requires_input", "blocked")
                ),
                RegenerationPlanStepRow.plan_id.in_(
                    nonterminal_plan_ids
                ),
            )
            .values(
                input_json=dumps(deepcopy(value)),
                status=status,
                blockers_json="[]",
                error="",
                claim_token="",
                claim_owner="",
                claim_until=None,
                updated_at=now,
                completed_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            raise ConflictError(
                "step changed while structured input was saved"
            )
        return self.get_step(step_id)


__all__ = [
    "CLAIMABLE_STEP_STATUSES",
    "NONTERMINAL_PLAN_STATUSES",
    "NONTERMINAL_STEP_STATUSES",
    "PLAN_STATUSES",
    "STEP_STATUSES",
    "TERMINAL_PLAN_STATUSES",
    "TERMINAL_STEP_STATUSES",
    "RegenerationPlanRepository",
]
