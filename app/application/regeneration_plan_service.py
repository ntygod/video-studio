"""Durable, restart-safe coordinator for regeneration plans."""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from typing import Any

from app.application.commands.base import (
    CommandBus,
    CommandContext,
)
from app.application.regeneration_service import (
    prepare_artifact_regeneration,
)
from app.store import UnitOfWork
from app.store.regeneration_repository import (
    TERMINAL_PLAN_STATUSES,
)
from app.store.repositories import ConflictError, NotFoundError

_PLAN_LOCKS: dict[str, threading.Lock] = {}
_PLAN_LOCKS_GUARD = threading.Lock()


def _plan_lock(plan_id: str) -> threading.Lock:
    with _PLAN_LOCKS_GUARD:
        return _PLAN_LOCKS.setdefault(plan_id, threading.Lock())


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
                            "regeneration Job succeeded without the expected "
                            "Artifact version result"
                        ),
                    )
                    continue
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "succeeded",
                    result=deepcopy(result),
                )
            elif job["status"] == "failed":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "failed",
                    error=job.get("error") or "regeneration Job failed",
                )
            elif job["status"] == "canceled":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "canceled",
                    error="regeneration Job was canceled",
                )
            elif job["status"] == "running":
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "running",
                )
            else:
                uow.regeneration_plans.set_step_status(
                    step["id"],
                    "queued",
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


def _schedule_llm_step(database, step: dict[str, Any], engine=None) -> None:
    from app.application.commands import CreateJobCommand

    with UnitOfWork(database) as uow:
        current = uow.regeneration_plans.get_step(step["id"])
        plan = uow.regeneration_plans.get(current["plan_id"])
        if plan["status"] != "running":
            return
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

    execution = CommandBus(database).execute(
        CreateJobCommand(
            project_id=project_id,
            unit_id=unit_id,
            job_type="generate",
            payload=payload,
        ),
        CommandContext(
            actor_type="system",
            actor_id=step["plan_id"],
            idempotency_key=(
                f"regeneration-plan:{step['plan_id']}:"
                f"step:{step['id']}"
            ),
        ),
    )
    job = execution.result
    with UnitOfWork(database) as uow:
        plan = uow.regeneration_plans.get(step["plan_id"])
        if plan["status"] != "running":
            uow.jobs.request_cancel(job["id"])
            uow.regeneration_plans.set_step_status(
                step["id"],
                "canceled",
                job_id=job["id"],
                error="plan stopped before the Job was linked",
            )
            return
        uow.regeneration_plans.set_step_status(
            step["id"],
            "queued",
            job_id=job["id"],
        )
    if engine is not None and job["status"] == "queued":
        engine.submit(job["id"])


def _execute_local_step(database, step: dict[str, Any]) -> None:
    from app.application.commands import (
        RecompileTimelineArtifactCommand,
        RepairTimelineAssetsCommand,
    )

    context = CommandContext(
        actor_type="system",
        actor_id=step["plan_id"],
        idempotency_key=(
            f"regeneration-plan:{step['plan_id']}:"
            f"step:{step['id']}"
        ),
    )
    if step["action"] == "recompile_timeline":
        execution = CommandBus(database).execute(
            RecompileTimelineArtifactCommand(
                artifact_id=step["artifact_id"],
                expected_current_version_id=str(
                    step["expected_version_id"] or ""
                ),
            ),
            context,
        )
    elif step["action"] == "repair_timeline_assets":
        replacements = dict(
            (step.get("input") or {}).get("replacements") or {}
        )
        if not replacements:
            raise ConflictError(
                "Timeline repair step has no Asset replacements"
            )
        execution = CommandBus(database).execute(
            RepairTimelineAssetsCommand(
                artifact_id=step["artifact_id"],
                replacements=replacements,
                expected_current_version_id=str(
                    step["expected_version_id"] or ""
                ),
            ),
            context,
        )
    else:
        raise ConflictError(
            f"unsupported local regeneration action: {step['action']}"
        )
    result = execution.result
    artifact = result.get("artifact") or {}
    version = artifact.get("current_version") or {}
    with UnitOfWork(database) as uow:
        uow.regeneration_plans.set_step_status(
            step["id"],
            "succeeded",
            result={
                "artifact_id": artifact.get("id"),
                "version_id": version.get("id"),
                "operation_id": execution.operation["id"],
            },
        )


def _finish_plan_state(database, plan_id: str) -> dict[str, Any]:
    with UnitOfWork(database) as uow:
        plan = uow.regeneration_plans.get(plan_id)
        steps = plan["steps"]
        summary = _runtime_summary(steps)
        uow.regeneration_plans.update_summary(plan_id, summary)
        statuses = {step["status"] for step in steps}
        if "failed" in statuses:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "failed",
                error="one or more regeneration steps failed",
            )
        elif "canceled" in statuses:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "canceled",
                error="one or more regeneration steps were canceled",
            )
        elif all(
            step["status"] in {"skipped", "succeeded"}
            for step in steps
        ):
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "succeeded",
            )
        elif any(
            step["status"] in {"queued", "running"}
            for step in steps
        ):
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "running",
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
            )
        else:
            uow.regeneration_plans.set_plan_status(
                plan_id,
                "running",
            )
        return uow.regeneration_plans.get(plan_id)


def advance_regeneration_plan(
    database,
    plan_id: str,
    engine=None,
) -> dict[str, Any]:
    """Advance every currently releasable step without waiting for Jobs."""

    with _plan_lock(plan_id):
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
                if step["status"] not in {
                    "ready",
                    "waiting_for_predecessors",
                }:
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
                            "A required predecessor cannot complete automatically.",
                            predecessor["artifact_id"],
                        )
                    with UnitOfWork(database) as uow:
                        uow.regeneration_plans.set_step_status(
                            step["id"],
                            "blocked",
                            blockers=blockers,
                            error="regeneration predecessor is not resolvable",
                        )
                    continue
                if not all(
                    predecessor["status"] in {"skipped", "succeeded"}
                    for predecessor in predecessors
                ):
                    continue

                try:
                    if step["action"] == "regenerate_llm":
                        _schedule_llm_step(database, step, engine)
                        scheduled_async = True
                    elif step["action"] in {
                        "recompile_timeline",
                        "repair_timeline_assets",
                    }:
                        _execute_local_step(database, step)
                        made_local_progress = True
                    else:
                        raise ConflictError(
                            "step action is not executable automatically: "
                            + step["action"]
                        )
                except Exception as exc:
                    with UnitOfWork(database) as uow:
                        uow.regeneration_plans.set_step_status(
                            step["id"],
                            "failed",
                            error=str(exc),
                        )

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
            # A step-level failure is persisted by the coordinator. Recovery
            # must continue scanning other plans even if one legacy plan is bad.
            continue
    return len(plan_ids)


__all__ = [
    "advance_plan_for_job",
    "advance_regeneration_plan",
    "recover_regeneration_plans",
    "regeneration_preview_snapshot_sha256",
]
