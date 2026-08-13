"""Runtime ownership contract for externally executed media Jobs.

A Job remains the product-facing task record, while exactly one RuntimePlan /
RuntimeTask owns scheduling, lease recovery, attempts, and cancellation. The
legacy Job queue must never claim a Job once these links are present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MEDIA_JOB_PLAN_KIND = "job.media"
TTS_JOB_PLAN_KIND = "job.tts"
MEDIA_JOB_TASK_TYPE = "job.media.execute"
TTS_JOB_TASK_TYPE = "job.tts.execute"
VOICE_JOB_TASK_TYPE = "job.voice.execute"
RUNTIME_JOB_PLAN_KINDS = frozenset(
    {MEDIA_JOB_PLAN_KIND, TTS_JOB_PLAN_KIND}
)


@dataclass(frozen=True, slots=True)
class RuntimeJobSpec:
    plan_kind: str
    task_type: str
    timeout_seconds: float


def runtime_job_spec(
    job_type: str,
    payload: dict[str, Any] | None,
) -> RuntimeJobSpec | None:
    normalized_type = str(job_type or "").strip().lower()
    data = dict(payload or {})
    capability = str(data.get("capability") or "").strip().lower()

    if capability == "image":
        return RuntimeJobSpec(
            MEDIA_JOB_PLAN_KIND,
            MEDIA_JOB_TASK_TYPE,
            30 * 60,
        )
    if capability == "video":
        return RuntimeJobSpec(
            MEDIA_JOB_PLAN_KIND,
            MEDIA_JOB_TASK_TYPE,
            2 * 60 * 60,
        )
    if capability == "tts" or normalized_type == "tts":
        return RuntimeJobSpec(
            TTS_JOB_PLAN_KIND,
            TTS_JOB_TASK_TYPE,
            30 * 60,
        )
    if normalized_type == "voice_synthesis":
        return RuntimeJobSpec(
            TTS_JOB_PLAN_KIND,
            VOICE_JOB_TASK_TYPE,
            2 * 60 * 60,
        )
    return None


def attach_runtime_job(uow, job: dict[str, Any]) -> dict[str, Any]:
    """Create and link the one RuntimePlan that owns this Job generation.

    The caller must invoke this in the same transaction that creates or resets
    the Job. Replays return the already linked execution identity.
    """

    spec = runtime_job_spec(job["job_type"], job.get("payload") or {})
    if spec is None:
        return {
            "job": job,
            "plan": None,
            "task": None,
        }

    existing_plan_id = str(job.get("runtime_plan_id") or "")
    existing_task_id = str(job.get("runtime_task_id") or "")
    if existing_plan_id or existing_task_id:
        if not existing_plan_id or not existing_task_id:
            raise RuntimeError(
                "Job has an incomplete Runtime execution link"
            )
        return {
            "job": job,
            "plan": uow.task_runtime.get_plan(existing_plan_id),
            "task": uow.task_runtime.get_task(existing_task_id),
        }

    generation = max(1, int(job.get("runtime_generation") or 1))
    plan = uow.task_runtime.create_plan(
        project_id=job["project_id"],
        kind=spec.plan_kind,
        subject_type="job",
        subject_id=job["id"],
        idempotency_key=(
            f"job:{job['id']}:runtime-generation:{generation}"
        ),
        input={
            "job_id": job["id"],
            "job_type": job["job_type"],
            "capability": str(
                (job.get("payload") or {}).get("capability") or ""
            ),
            "runtime_generation": generation,
        },
        policy={"runtime_job_contract_version": 1},
    )
    task = uow.task_runtime.add_task(
        plan["id"],
        task_key="execute",
        task_type=spec.task_type,
        payload={
            "job_id": job["id"],
            "runtime_generation": generation,
        },
        max_attempts=max(1, int(job.get("max_attempts") or 3)),
        timeout_seconds=spec.timeout_seconds,
    )
    uow.task_runtime.queue_plan(plan["id"])
    linked = uow.jobs.link_runtime_execution(
        job["id"],
        plan_id=plan["id"],
        task_id=task["id"],
        generation=generation,
    )
    return {
        "job": linked,
        "plan": uow.task_runtime.get_plan(plan["id"]),
        "task": uow.task_runtime.get_task(task["id"]),
    }


__all__ = [
    "MEDIA_JOB_PLAN_KIND",
    "MEDIA_JOB_TASK_TYPE",
    "RUNTIME_JOB_PLAN_KINDS",
    "RuntimeJobSpec",
    "TTS_JOB_PLAN_KIND",
    "TTS_JOB_TASK_TYPE",
    "VOICE_JOB_TASK_TYPE",
    "attach_runtime_job",
    "runtime_job_spec",
]
