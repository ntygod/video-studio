"""DB queue claim and lease for legacy, non-Runtime Jobs."""

import time

from sqlalchemy import text

from app.store import UnitOfWork

LEASE_SECONDS = 60


def claim(database, worker_id: str, lease_seconds: int = LEASE_SECONDS):
    """Atomically claim one legacy queued Job.

    Jobs linked to a RuntimePlan are deliberately invisible here. Their lease,
    attempts, timeout, and recovery are owned exclusively by RuntimeTask.
    """

    now = time.time()
    with database.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM jobs "
                "WHERE status='queued' "
                "AND runtime_plan_id IS NULL "
                "AND (lease_until IS NULL OR lease_until <= :now) "
                "ORDER BY created_at LIMIT 1"
            ),
            {"now": now},
        ).first()
        if row is None:
            return None
        job_id = row[0]
        result = conn.execute(
            text(
                "UPDATE jobs SET status='running', worker_id=:wid, "
                "lease_until=:until, updated_at=:now, attempt=attempt+1 "
                "WHERE id=:id AND status='queued' "
                "AND runtime_plan_id IS NULL"
            ),
            {
                "wid": worker_id,
                "until": now + lease_seconds,
                "now": now,
                "id": job_id,
            },
        )
        if result.rowcount != 1:
            return None
    with UnitOfWork(database) as uow:
        return uow.jobs.get(job_id)


def renew(database, job_ids: list[str], lease_seconds: int = LEASE_SECONDS) -> int:
    """Renew leases for still-running legacy Jobs."""

    if not job_ids:
        return 0
    placeholders = ", ".join(
        f":id{index}" for index in range(len(job_ids))
    )
    params: dict[str, object] = {
        f"id{index}": job_id
        for index, job_id in enumerate(job_ids)
    }
    params["until"] = time.time() + lease_seconds
    with database.engine.begin() as conn:
        result = conn.execute(
            text(
                f"UPDATE jobs SET lease_until=:until "
                f"WHERE status='running' "
                f"AND runtime_plan_id IS NULL "
                f"AND id IN ({placeholders})"
            ),
            params,
        )
        return result.rowcount


def recover(database) -> int:
    """Return only expired legacy Jobs to the old queue."""

    now = time.time()
    with database.engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE jobs SET status='queued', worker_id='', "
                "lease_until=NULL "
                "WHERE status='running' "
                "AND runtime_plan_id IS NULL "
                "AND lease_until < :now"
            ),
            {"now": now},
        )
        return result.rowcount


def mark_backoff(database, job_id: str, seconds: float) -> None:
    with database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET lease_until=:until "
                "WHERE id=:id AND runtime_plan_id IS NULL"
            ),
            {"until": time.time() + seconds, "id": job_id},
        )
