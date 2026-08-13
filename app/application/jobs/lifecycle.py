"""Explicit Job lifecycle operations shared by HTTP and workers."""

from __future__ import annotations

from app.application.jobs.runtime_contract import attach_runtime_job
from app.store import UnitOfWork
from app.store.repositories import ConflictError
from app.store.task_runtime_repository import TERMINAL_PLAN_STATUSES

RETRYABLE_STATUSES = frozenset({"failed", "canceled"})


def reset_job_for_retry(database, job_id: str) -> dict:
    """Create a fresh Job execution generation without rewriting history."""

    with UnitOfWork(database) as uow:
        current = uow.jobs.get(job_id)
        if current["status"] not in RETRYABLE_STATUSES:
            raise ConflictError(
                "只有失败或已取消的任务可以重试"
            )
        old_plan_id = str(current.get("runtime_plan_id") or "")
        if old_plan_id:
            old_plan = uow.task_runtime.get_plan(old_plan_id)
            if old_plan["status"] not in TERMINAL_PLAN_STATUSES:
                raise ConflictError(
                    "耐久任务仍在结束处理中，请刷新后重试"
                )
        reset = uow.jobs.reset_for_retry(job_id)
        attach_runtime_job(uow, reset)
        uow.jobs.add_event(
            job_id,
            "用户已重新发起任务",
            stage="retry",
            progress=0.0,
        )
        # Preserve the public repository contract: lifecycle callers receive
        # the same full Job shape as GET /api/jobs/{id}, including events.
        return uow.jobs.get(job_id)
