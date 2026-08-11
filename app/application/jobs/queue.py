"""DB 队列认领与 lease。"""

import time

from sqlalchemy import text

from app.store import UnitOfWork

#: 认领后 lease 的有效期。worker 必须在到期前续约，否则会被 recover 判定为掉线。
LEASE_SECONDS = 60


def claim(database, worker_id: str, lease_seconds: int = LEASE_SECONDS):
    """原子认领一个 queued 任务：置 running、登记 worker 与 lease、attempt+1。

    两个 worker 并发认领同一任务时，UPDATE 的 rowcount=0 的一方返回 None。
    """
    now = time.time()
    with database.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM jobs "
                "WHERE status='queued' AND (lease_until IS NULL OR lease_until <= :now) "
                "ORDER BY created_at LIMIT 1"
            ),
            {"now": now},
        ).first()
        if row is None:
            return None
        job_id = row[0]
        result = conn.execute(
            text(
                "UPDATE jobs SET status='running', worker_id=:wid, lease_until=:until, "
                "updated_at=:now, attempt=attempt+1 "
                "WHERE id=:id AND status='queued'"
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
    """为仍在运行的任务续约 lease。

    没有续约的话，任何耗时超过 LEASE_SECONDS 的任务（视频生成、渲染都轻易超过）
    都会被 recover 打回 queued，然后被另一个 worker 重复认领——两个 worker 同时
    跑同一个任务，产出重复素材。
    """
    if not job_ids:
        return 0
    placeholders = ", ".join(f":id{index}" for index in range(len(job_ids)))
    params: dict[str, object] = {f"id{index}": job_id for index, job_id in enumerate(job_ids)}
    params["until"] = time.time() + lease_seconds
    with database.engine.begin() as conn:
        result = conn.execute(
            text(
                f"UPDATE jobs SET lease_until=:until "
                f"WHERE status='running' AND id IN ({placeholders})"
            ),
            params,
        )
        return result.rowcount


def recover(database) -> int:
    """把 lease 过期的 running 任务打回 queued（进程崩溃/杀服务后恢复）。"""
    now = time.time()
    with database.engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE jobs SET status='queued', worker_id='', lease_until=NULL "
                "WHERE status='running' AND lease_until < :now"
            ),
            {"now": now},
        )
        return result.rowcount


def mark_backoff(database, job_id: str, seconds: float) -> None:
    """把重试任务的 lease_until 设为 now+seconds，claim 会等到退避结束再认领。"""
    with database.engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET lease_until=:until WHERE id=:id"),
            {"until": time.time() + seconds, "id": job_id},
        )
