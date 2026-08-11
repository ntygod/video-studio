"""持久化任务事件的增量查询。

API 的任务列表是轻量摘要，不应为了 SSE 给每个任务做一次事件查询。这里用
``(created_at, id)`` 游标一次性读取匹配项目的新事件，供长连接持续消费。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def list_job_events_after(
    database,
    *,
    project_id: str | None = None,
    after_created_at: float = 0.0,
    after_id: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """按稳定游标返回后续任务事件。

    ``created_at`` 是主排序键，``id`` 用于同一时间戳下的稳定排序。返回数量有界，
    防止一个积压连接单次占用过多内存。
    """

    limit = max(1, min(int(limit), 2000))
    project_clause = ""
    params: dict[str, Any] = {
        "after_created_at": float(after_created_at),
        "after_id": str(after_id),
        "limit": limit,
    }
    if project_id:
        project_clause = "AND j.project_id = :project_id"
        params["project_id"] = project_id

    query = text(
        f"""
        SELECT
            e.id,
            e.job_id,
            e.level,
            e.stage,
            e.message,
            e.progress,
            e.created_at
        FROM job_events AS e
        JOIN jobs AS j ON j.id = e.job_id
        WHERE (
            e.created_at > :after_created_at
            OR (e.created_at = :after_created_at AND e.id > :after_id)
        )
        {project_clause}
        ORDER BY e.created_at ASC, e.id ASC
        LIMIT :limit
        """
    )

    with database.engine.connect() as connection:
        rows = connection.execute(query, params).mappings().all()
    return [dict(row) for row in rows]
