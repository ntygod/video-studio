"""Job 状态机中的显式生命周期操作。

Repository 的通用 ``update_state`` 适合 worker 推进状态，但手动重试需要一次性
清理取消标记、lease、worker、旧结果和 attempt。把这条规则集中在这里，避免 API
端遗漏字段后让任务一认领就再次取消。
"""

from __future__ import annotations

import time

from sqlalchemy import text

from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError

RETRYABLE_STATUSES = frozenset({"failed", "canceled"})


def reset_job_for_retry(database, job_id: str) -> dict:
    """把失败或取消的任务原子重置为一次全新的执行。

    历史事件保留用于审计；payload、parent/turn 关联和 ``max_attempts`` 保留。
    ``attempt`` 归零，表示用户显式发起了一个新的重试预算。
    """

    now = time.time()
    with database.engine.begin() as connection:
        status = connection.execute(
            text("SELECT status FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).scalar_one_or_none()
        if status is None:
            raise NotFoundError(job_id)
        if status not in RETRYABLE_STATUSES:
            raise ConflictError("只有失败或已取消的任务可以重试")

        updated = connection.execute(
            text(
                """
                UPDATE jobs
                SET status = 'queued',
                    progress = 0.0,
                    cancel_requested = 0,
                    attempt = 0,
                    lease_until = NULL,
                    worker_id = '',
                    result_json = NULL,
                    error = '',
                    updated_at = :updated_at
                WHERE id = :job_id
                  AND status = :expected_status
                """
            ),
            {
                "job_id": job_id,
                "expected_status": status,
                "updated_at": now,
            },
        )
        if updated.rowcount != 1:
            raise ConflictError("任务状态已变化，请刷新后重试")

    with UnitOfWork(database) as uow:
        uow.jobs.add_event(
            job_id,
            "用户已重新发起任务",
            stage="retry",
            progress=0.0,
        )
        return uow.jobs.get(job_id)
