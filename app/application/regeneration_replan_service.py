"""Validation and queries for immutable regeneration replan lineage."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from app.store.regeneration_replan_models import (
    RegenerationPlanReplanRow,
)
from app.store.repositories import ConflictError, NotFoundError

ALLOWED_REPLAN_SOURCE_STATUSES = frozenset(
    {"draft", "blocked", "failed", "canceled"}
)
MAX_REPLAN_REASON_LENGTH = 2000


def _relation(row: RegenerationPlanReplanRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_plan_id": row.source_plan_id,
        "target_plan_id": row.target_plan_id,
        "source_status": row.source_status,
        "source_execution_attempt": row.source_execution_attempt,
        "target_snapshot_sha256": row.target_snapshot_sha256,
        "reason": row.reason,
        "created_at": row.created_at,
    }


def relation_from_source(uow, plan_id: str):
    return uow.session.scalar(
        select(RegenerationPlanReplanRow).where(
            RegenerationPlanReplanRow.source_plan_id == plan_id
        )
    )


def relation_to_target(uow, plan_id: str):
    return uow.session.scalar(
        select(RegenerationPlanReplanRow).where(
            RegenerationPlanReplanRow.target_plan_id == plan_id
        )
    )


def get_regeneration_plan_lineage(
    uow,
    plan_id: str,
) -> dict[str, Any]:
    plan = uow.regeneration_plans.get(plan_id)
    parent = relation_to_target(uow, plan_id)
    child = relation_from_source(uow, plan_id)
    return {
        "plan_id": plan_id,
        "project_id": plan["project_id"],
        "replanned_from": _relation(parent) if parent else None,
        "replanned_by": _relation(child) if child else None,
    }


def validate_replan_source(
    uow,
    plan_id: str,
    *,
    expected_status: str,
    expected_execution_attempt: int,
) -> dict[str, Any]:
    """Require a settled, non-successful Plan with no existing child."""

    plan = uow.regeneration_plans.get(plan_id)
    status = str(plan["status"])
    if status != str(expected_status):
        raise ConflictError(
            "regeneration Plan status changed before replan: "
            f"expected {expected_status}, found {status}"
        )
    if status not in ALLOWED_REPLAN_SOURCE_STATUSES:
        raise ConflictError(
            f"regeneration Plan status cannot be replanned: {status}"
        )
    if int(plan.get("execution_attempt") or 0) != int(
        expected_execution_attempt
    ):
        raise ConflictError(
            "regeneration Plan execution attempt changed before replan"
        )
    existing = relation_from_source(uow, plan_id)
    if existing is not None:
        raise ConflictError(
            "regeneration Plan was already replanned as "
            + existing.target_plan_id
        )
    if not plan.get("root_artifact_ids"):
        raise ConflictError(
            "regeneration Plan has no root Artifacts to replan"
        )

    now = time.time()
    for step in plan.get("steps") or []:
        if step.get("claimed") and (
            step.get("claim_until") is None
            or float(step["claim_until"]) > now
        ):
            raise ConflictError(
                "regeneration Plan still has a live Step claim"
            )
        job_id = str(step.get("job_id") or "")
        if not job_id:
            continue
        try:
            job = uow.jobs.get(job_id)
        except NotFoundError:
            continue
        if job["status"] in {"queued", "running"}:
            raise ConflictError(
                "regeneration Plan still has an active child Job: "
                + job_id
            )
    return plan


def normalized_replan_reason(reason: str) -> str:
    return str(reason or "").strip()[:MAX_REPLAN_REASON_LENGTH]


__all__ = [
    "ALLOWED_REPLAN_SOURCE_STATUSES",
    "MAX_REPLAN_REASON_LENGTH",
    "get_regeneration_plan_lineage",
    "normalized_replan_reason",
    "relation_from_source",
    "relation_to_target",
    "validate_replan_source",
]
