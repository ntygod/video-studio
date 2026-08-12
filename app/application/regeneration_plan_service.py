"""Durable, multi-process-safe coordinator for regeneration plans."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.application.commands.base import (
    CommandBus,
    CommandContext,
)
from app.application.regeneration_service import (
    prepare_artifact_regeneration,
)
from app.store import UnitOfWork
from app.store.regeneration_repository import (
    CLAIMABLE_STEP_STATUSES,
    NONTERMINAL_PLAN_STATUSES,
)
from app.store.repositories import ConflictError, NotFoundError

STEP_CLAIM_LEASE_SECONDS = 120.0
_COORDINATOR_ID = (
    f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"
)


class _StepDispatchDeferred(RuntimeError):
    """Another live coordinator is still executing the same Operation."""


def _step_operation_key(step: dict[str, Any]) -> str:
    return (
        f"regeneration-plan:{step['plan_id']}:"
        f"step:{step['id']}"
    )


def _operation_status(database, key: str) -> str | None:
    with UnitOfWork(database) as uow:
        operation = uow.operations.find_by_idempotency_key(key)
    return str(operation["status"]) if operation else None


def _execute_step_command(database, step, command):
    key = _step_operation_key(step)
    if _operation_status(database, key) == "running":
        raise _StepDispatchDeferred(
            "the same regeneration step Operation is still running"
        )
    try:
        return CommandBus(database).execute(
            command,
            CommandContext(
                actor_type="system",
                actor_id=step["plan_id"],
                idempotency_key=key,
            ),
        )
    except ConflictError:
        if _operation_status(database, key) == "running":
            raise _StepDispatchDeferred(
                "the same regeneration step Operation is still running"
            )
        raise


def regeneration_preview_snapshot_sha256(
    preview: dict[str, Any],
) -> str:
    """Hash only fields that define execution identity and safety."""

    normalized = {
        "project_id": preview.get("project_id"),
        "root_artifact_ids": preview.get("root_artifact_ids") or [],
        "include_downstream": bool(
            preview.get("include_downstream", True)
        ),
        "order": preview.get("order") or [],
        "steps": [
            {
                "artifact_id": item.get("artifact_id"),
                "expected_current_version_id": item.get(
                    "expected_current_version_id"
                ),
                "action": item.get("action"),
                "execution_state": item.get("execution_state"),
                "depends_on": item.get("depends_on") or [],
                "external_upstream_artifact_ids": item.get(
                    "external_upstream_artifact_ids"
                )
                or [],
                "direct_missing_asset_ids": item.get(
                    "direct_missing_asset_ids"
                )
                or [],
                "blockers": item.get("blockers") or [],
            }
            for item in preview.get("steps") or []
        ],
    }
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for step in steps:
        status = str(step["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "total": len(steps),
        "automatable": sum(
            1 for step in steps if step["can_execute_automatically"]
        ),
        "statuses": counts,
        "completed": sum(
            counts.get(status, 0)
            for status in ("skipped", "succeeded")
        ),
        "failed": counts.get("failed", 0),
        "canceled": counts.get("canceled", 0),
        "claimed": sum(1 for step in steps if step.get("claimed")),
    }


def _append_blocker(
    step: dict[str, Any],
    code: str,
    message: str,
    artifact_id: str | None = None,
) -> list[dict[str, Any]]:
    blockers = list(step.get("blockers") or [])
    item: dict[str, Any] = {"code": code, "message": message}
    if artifact_id:
        item.update(
            {
                "entity_type": "artifact",
                "entity_id": artifact_id,
            }
        )
    if not any(
        existing.get("code") == code
        and existing.get("entity_id") == artifact_id
        for existing in blockers
    ):
        blockers.append(item)
    return blockers


def _reconcile_job_steps(database, plan_id: str) -> None:
    with UnitOfWork(database) as uow:
        plan = uow.regeneration_plans.get(plan_id)
        for step in plan["steps"]:
            if (
                not step.get("job_id")
                or step["status"] not in {"queued", "running"}
            ):
                continue
            try:
                job = uow.jobs.get(step["job_id"])
            except NotFoundError:
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "failed",
                    error="regeneration step Job no longer exists",
                    expected_statuses={"queued", "running"},
                )
                continue
            if job["status"] == "succeeded":
                result = job.get("result") or {}
                if (
                    result.get("artifact_id") != step["artifact_id"]
                    or not result.get("version_id")
                ):
                    uow.regeneration_plans.set_step_status(
                        step["id"],
                        "failed",
                        error=(
                            "regeneration Job succeeded without the "
                            "expected Artifact version result"
                        ),
                        expected_statuses={"queued", "running"},
                    )
                    continue
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "succeeded",
                    result=deepcopy(result),
                    expected_statuses={"queued", "running"},
                )
            elif job["status"] == "failed":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "failed",
                    error=job.get("error")
                    or "regeneration Job failed",
                    expected_statuses={"queued", "running"},
                )
            elif job["status"] == "canceled":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "canceled",
                    error="regeneration Job was canceled",
                    expected_statuses={"queued", "running"},
                )
            elif job["status"] == "running":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "running",
                    expected_statuses={"queued", "running"},
                )
            else:
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "queued",
                    expected_statuses={"queued", "running"},
                )


def _assert_step_target_is_current(uow, step: dict[str, Any]) -> None:
    artifact = uow.artifacts.get(step["artifact_id"])
    if artifact["project_id"] != step["project_id"]:
        raise ConflictError(
            "regeneration step target belongs to another project"
        )
    if artifact.get("current_version_id") != step.get(
        "expected_version_id"
    ):
        raise ConflictError(
            "regeneration step target version changed: "
            + step["artifact_id"]
        )


def _schedule_llm_step(
    database,
    step: dict[str, Any],
    engine=None,
) -> tuple[bool, bool]:
    from app.application.commands import CreateJobCommand

    claim_token = str(step["_claim_token"])
    with UnitOfWork(database) as uow:
        if not uow.regeneration_plans.owns_step_claim(
            step["id"],
            claim_token,
        ):
            return False, False
        current = uow.regeneration_plans.get_step(step["id"])
        plan = uow.regeneration_plans.get(current["plan_id"])
        if plan["status"] != "running":
            uow.regeneration_plans.release_step_claim(
                current["id"],
                claim_token,
            )
            return False, False
        _assert_step_target_is_current(uow, current)
        specification = prepare_artifact_regeneration(
            uow,
            current["artifact_id"],
        )
        if specification["expected_target_version_id"] != current[
            "expected_version_id"
        ]:
            raise ConflictError(
                "regeneration specification no longer matches the plan"
            )
        payload = {
            **specification["payload"],
            "_regeneration_plan_id": plan["id"],
            "_regeneration_plan_step_id": current["id"],
        }
        project_id = plan["project_id"]
        unit_id = specification["unit_id"]

    execution = _execute_step_command(
        database,
        step,
        CreateJobCommand(
            project_id=project_id,
            unit_id=unit_id,
            job_type="generate",
            payload=payload,
        ),
    )
    job = execution.result
    with UnitOfWork(database) as uow:
        linked = uow.regeneration_plans.complete_step_claim(
            step["id"],
            claim_token,
            "queued",
            job_id=job["id"],
        )
        if linked is None:
            current = uow.regeneration_plans.get_step(step["id"])
            plan = uow.regeneration_plans.get(current["plan_id"])
            if (
                plan["status"] != "running"
                or current["status"] in {"canceled", "failed"}
            ):
                try:
                    uow.jobs.request_cancel(job["id"])
                except NotFoundError:
                    pass
            return False, False

    if engine is not None and job["status"] == "queued":
        engine.submit(job["id"])

    waiting = job["status"] in {"queued", "running"}
    if not waiting:
        _reconcile_job_steps(database, step["plan_id"])
    return True, waiting


def _execute_local_step(
    database,
    step: dict[str, Any],
) -> bool:
    from app.application.commands import (
        RecompileTimelineArtifactCommand,
        RepairTimelineAssetsCommand,
    )

    claim_token = str(step["_claim_token"])
    with UnitOfWork(database) as uow:
        if not uow.regeneration_plans.owns_step_claim(
            step["id"],
            claim_token,
        ):
            return False
        current = uow.regeneration_plans.get_step(step["id"])
        plan = uow.regeneration_plans.get(current["plan_id"])
        if plan["status"] != "running":
            uow.regeneration_plans.release_step_claim(
                current["id"],
                claim_token,
            )
            return False
        _assert_step_target_is_current(uow, current)

    if step["action"] == "recompile_timeline":
        command = RecompileTimelineArtifactCommand(
            artifact_id=step["artifact_id"],
            expected_current_version_id=str(
                step["expected_version_id"] or ""
            ),
        )
    elif step["action"] == "repair_timeline_assets":
        replacements = dict(
            (step.get("input") or {}).get("replacements") or {}
        )
        if not replacements:
            raise ConflictError(
                "Timeline repair step has no Asset replacements"
            )
        command = RepairTimelineAssetsCommand(
            artifact_id=step["artifact_id"],
            replacements=replacements,
            expected_current_version_id=str(
                step["expected_version_id"] or ""
            ),
        )
    else:
        raise ConflictError(
            "unsupported local regeneration action: "
            + step["action"]
        )

    execution = _execute_step_command(database, step, command)
    result = execution.result
    artifact = result.get("artifact") or {}
    version = artifact.get("current_version") or {}
    with UnitOfWork(database) as uow:
        completed = uow.regeneration_plans.complete_step_claim(
            step["id"],
            claim_token,
            "succeeded",
            result={
                "artifact_id": artifact.get("id"),
                "version_id": version.get("id"),
                "operation_id": execution.operation["id"],
            },
        )
    return completed is not None


def _release_claim(database, step: dict[str, Any]) -> None:
    with UnitOfWork(database) as uow:
        uow.regeneration_plans.release_step_claim(
            step["id"],
            str(step["_claim_token"]),
        )


def _fail_claim(
    database,
    step: dict[str, Any],
    error: str,
) -> bool:
    with UnitOfWork(database) as uow:
        failed = uow.regeneration_plans.complete_step_claim(
            step["id"],
            str(step["_claim_token"]),
            "failed",
            error=error,
        )
    return failed is not None


def _finish_plan_state(database, plan_id: str) -> dict[str, Any]:
    with UnitOfWork(database) as uow:
        plan = uow.regeneration_plans.get(plan_id)
        if plan["status"] not in NONTERMINAL_PLAN_STATUSES:
            return plan
        steps = plan["steps"]
        summary = _runtime_summary(steps)
        uow.regeneration_plans.update_summary(plan_id, summary)
        statuses = {step["status"] for step in steps}
        expected = NONTERMINAL_PLAN_STATUSES
        if "failed" in statuses:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "failed",
                error="one or more regeneration steps failed",
                expected_statuses=expected,
            )
        elif "canceled" in statuses:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "canceled",
                error="one or more regeneration steps were canceled",
                expected_statuses=expected,
            )
        elif all(
            step["status"] in {"skipped", "succeeded"}
            for step in steps
        ):
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "succeeded",
                expected_statuses=expected,
            )
        elif any(
            step["status"] in {"queued", "running"}
            for step in steps
        ):
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "running",
                expected_statuses=expected,
            )
        elif any(
            step["status"]
            in {
                "requires_input",
                "requires_review",
                "manual",
                "blocked",
            }
            for step in steps
        ):
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "blocked",
                expected_statuses=expected,
            )
        else:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "running",
                expected_statuses=expected,
            )
        return uow.regeneration_plans.get(plan_id)


def advance_regeneration_plan(
    database,
    plan_id: str,
    engine=None,
    *,
    coordinator_id: str | None = None,
    claim_lease_seconds: float = STEP_CLAIM_LEASE_SECONDS,
) -> dict[str, Any]:
    """Advance releasable Steps using database compare-and-set leases."""

    owner = coordinator_id or _COORDINATOR_ID
    for _iteration in range(1000):
        _reconcile_job_steps(database, plan_id)
        with UnitOfWork(database) as uow:
            plan = uow.regeneration_plans.get(plan_id)
        if plan["status"] != "running":
            return plan

        steps = plan["steps"]
        by_artifact = {
            step["artifact_id"]: step for step in steps
        }
        made_local_progress = False
        scheduled_async = False

        for step in steps:
            if step["status"] not in CLAIMABLE_STEP_STATUSES:
                continue
            predecessors = [
                by_artifact[artifact_id]
                for artifact_id in step["depends_on_artifact_ids"]
                if artifact_id in by_artifact
            ]
            bad = [
                predecessor
                for predecessor in predecessors
                if predecessor["status"]
                in {
                    "failed",
                    "canceled",
                    "blocked",
                    "requires_input",
                    "requires_review",
                    "manual",
                }
            ]
            if bad:
                blockers = list(step["blockers"])
                for predecessor in bad:
                    blockers = _append_blocker(
                        {**step, "blockers": blockers},
                        "predecessor_not_succeeded",
                        (
                            "A required predecessor cannot complete "
                            "automatically."
                        ),
                        predecessor["artifact_id"],
                    )
                with UnitOfWork(database) as uow:
                    uow.regeneration_plans.set_step_status(
                        step["id"],
                        "blocked",
                        blockers=blockers,
                        error=(
                            "regeneration predecessor is not resolvable"
                        ),
                        expected_statuses=CLAIMABLE_STEP_STATUSES,
                    )
                made_local_progress = True
                continue
            if not all(
                predecessor["status"] in {"skipped", "succeeded"}
                for predecessor in predecessors
            ):
                continue

            with UnitOfWork(database) as uow:
                claimed = uow.regeneration_plans.claim_step(
                    step["id"],
                    owner=owner,
                    lease_seconds=claim_lease_seconds,
                )
            if claimed is None:
                continue

            try:
                if claimed["action"] == "regenerate_llm":
                    linked, waiting = _schedule_llm_step(
                        database,
                        claimed,
                        engine,
                    )
                    if linked and waiting:
                        scheduled_async = True
                    elif linked:
                        made_local_progress = True
                elif claimed["action"] in {
                    "recompile_timeline",
                    "repair_timeline_assets",
                }:
                    if _execute_local_step(database, claimed):
                        made_local_progress = True
                else:
                    raise ConflictError(
                        "step action is not executable automatically: "
                        + claimed["action"]
                    )
            except _StepDispatchDeferred:
                _release_claim(database, claimed)
            except Exception as exc:
                if _fail_claim(database, claimed, str(exc)):
                    made_local_progress = True

        final = _finish_plan_state(database, plan_id)
        if final["status"] != "running":
            return final
        if scheduled_async or not made_local_progress:
            return final
    raise RuntimeError(
        "regeneration coordinator exceeded its progress iteration limit"
    )


def advance_plan_for_job(database, job_id: str, engine=None) -> None:
    try:
        with UnitOfWork(database) as uow:
            job = uow.jobs.get(job_id)
            payload = job.get("payload") or {}
            plan_id = str(
                payload.get("_regeneration_plan_id") or ""
            )
            if not plan_id:
                step = uow.regeneration_plans.find_step_by_job(job_id)
                plan_id = str((step or {}).get("plan_id") or "")
        if plan_id:
            advance_regeneration_plan(database, plan_id, engine)
    except NotFoundError:
        return


def recover_regeneration_plans(database, engine=None) -> int:
    with UnitOfWork(database) as uow:
        plan_ids = uow.regeneration_plans.active_ids()
    for plan_id in plan_ids:
        try:
            advance_regeneration_plan(database, plan_id, engine)
        except Exception:
            continue
    return len(plan_ids)


__all__ = [
    "STEP_CLAIM_LEASE_SECONDS",
    "advance_plan_for_job",
    "advance_regeneration_plan",
    "recover_regeneration_plans",
    "regeneration_preview_snapshot_sha256",
]
