"""Job repository extended with one durable Runtime execution owner."""

from __future__ import annotations

import time
from typing import Any

from .job_runtime_models import JobRuntimeLinkRow
from .models import JobRow
from .repositories import ConflictError, JobRepository, NotFoundError


class RuntimeLinkedJobRepository(JobRepository):
    def _link_row(self, job_id: str) -> JobRuntimeLinkRow:
        row = self.session.get(JobRuntimeLinkRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        return row

    def _data(self, row: JobRow) -> dict[str, Any]:
        data = JobRepository._data(row)
        link = self._link_row(row.id)
        data.update(
            {
                "runtime_plan_id": link.runtime_plan_id,
                "runtime_task_id": link.runtime_task_id,
                "runtime_generation": int(link.runtime_generation or 1),
            }
        )
        return data

    def link_runtime_execution(
        self,
        job_id: str,
        *,
        plan_id: str,
        task_id: str,
        generation: int,
    ) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        link = self._link_row(job_id)
        normalized_generation = max(1, int(generation))
        if int(link.runtime_generation or 1) != normalized_generation:
            raise ConflictError(
                "Job Runtime generation changed before it was linked"
            )
        if link.runtime_plan_id and link.runtime_plan_id != plan_id:
            raise ConflictError(
                "Job is already linked to another RuntimePlan"
            )
        if link.runtime_task_id and link.runtime_task_id != task_id:
            raise ConflictError(
                "Job is already linked to another RuntimeTask"
            )
        link.runtime_plan_id = str(plan_id)
        link.runtime_task_id = str(task_id)
        self.session.flush()
        return self._data(row)

    def begin_runtime_attempt(
        self,
        job_id: str,
        *,
        plan_id: str,
        task_id: str,
        generation: int,
        attempt: int,
        worker_id: str,
    ) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        link = self._link_row(job_id)
        if (
            link.runtime_plan_id != plan_id
            or link.runtime_task_id != task_id
            or int(link.runtime_generation or 1) != int(generation)
        ):
            raise ConflictError(
                "Job Runtime execution is no longer current"
            )
        row.status = "running"
        row.progress = 0.0
        row.attempt = max(1, int(attempt))
        row.worker_id = str(worker_id or "runtime")[:64]
        row.lease_until = None
        row.error = ""
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def reset_for_retry(self, job_id: str) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        if row.status not in {"failed", "canceled"}:
            raise ConflictError(
                "只有失败或已取消的任务可以重试"
            )
        link = self._link_row(job_id)
        link.runtime_generation = int(link.runtime_generation or 1) + 1
        link.runtime_plan_id = None
        link.runtime_task_id = None
        row.status = "queued"
        row.progress = 0.0
        row.cancel_requested = False
        row.attempt = 0
        row.lease_until = None
        row.worker_id = ""
        row.result_json = None
        row.error = ""
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)


__all__ = ["RuntimeLinkedJobRepository"]
