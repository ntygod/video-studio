"""Repository for the generic durable task runtime."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select, update

from .json_codec import dumps, loads
from .repositories import ConflictError, NotFoundError, new_id
from .task_runtime_models import (
    RuntimePlanRow,
    RuntimeTaskAttemptRow,
    RuntimeTaskEventRow,
    RuntimeTaskRow,
)

PLAN_STATUSES = frozenset(
    {
        "draft",
        "queued",
        "running",
        "blocked",
        "succeeded",
        "failed",
        "canceled",
    }
)
TASK_STATUSES = frozenset(
    {
        "queued",
        "running",
        "blocked",
        "skipped",
        "succeeded",
        "failed",
        "canceled",
    }
)
ATTEMPT_STATUSES = frozenset(
    {
        "running",
        "succeeded",
        "failed",
        "canceled",
        "interrupted",
        "timed_out",
    }
)
TERMINAL_PLAN_STATUSES = frozenset(
    {"succeeded", "failed", "canceled"}
)
TERMINAL_TASK_STATUSES = frozenset(
    {"blocked", "skipped", "succeeded", "failed", "canceled"}
)
ACTIVE_PLAN_STATUSES = frozenset({"queued", "running"})
MAX_TASK_SCAN = 200


def _normalized_statuses(
    values: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(dict.fromkeys(str(value) for value in values))


class TaskRuntimeRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _plan(row: RuntimePlanRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "kind": row.kind,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "idempotency_key": row.idempotency_key,
            "status": row.status,
            "priority": row.priority,
            "event_seq": row.event_seq,
            "input": loads(row.input_json, {}),
            "policy": loads(row.policy_json, {}),
            "budget": loads(row.budget_json, {}),
            "usage": loads(row.usage_json, {}),
            "result": loads(row.result_json, {}),
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }

    @staticmethod
    def _attempt(row: RuntimeTaskAttemptRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "task_id": row.task_id,
            "attempt": row.attempt,
            "status": row.status,
            "worker_id": row.worker_id,
            "claim_token": row.claim_token,
            "checkpoint": loads(row.checkpoint_json, {}),
            "result": loads(row.result_json, {}),
            "usage": loads(row.usage_json, {}),
            "error": row.error,
            "retryable": row.retryable,
            "started_at": row.started_at,
            "heartbeat_at": row.heartbeat_at,
            "lease_until": row.lease_until,
            "completed_at": row.completed_at,
        }

    @classmethod
    def _task(
        cls,
        row: RuntimeTaskRow,
        attempts: list[RuntimeTaskAttemptRow] | None = None,
    ) -> dict[str, Any]:
        result = {
            "id": row.id,
            "plan_id": row.plan_id,
            "project_id": row.project_id,
            "task_key": row.task_key,
            "task_type": row.task_type,
            "status": row.status,
            "priority": row.priority,
            "order_index": row.order_index,
            "depends_on_task_ids": loads(
                row.depends_on_task_ids_json,
                [],
            ),
            "payload": loads(row.payload_json, {}),
            "policy": loads(row.policy_json, {}),
            "checkpoint": loads(row.checkpoint_json, {}),
            "result": loads(row.result_json, {}),
            "usage": loads(row.usage_json, {}),
            "error": row.error,
            "attempt_count": row.attempt_count,
            "max_attempts": row.max_attempts,
            "timeout_seconds": row.timeout_seconds,
            "available_at": row.available_at,
            "cancel_requested": row.cancel_requested,
            "claimed": bool(row.claim_token),
            "claim_owner": row.claim_owner,
            "claim_until": row.claim_until,
            "claim_attempt": row.claim_attempt,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
        if attempts is not None:
            result["attempts"] = [cls._attempt(item) for item in attempts]
        return result

    @staticmethod
    def _event(row: RuntimeTaskEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "task_id": row.task_id,
            "attempt_id": row.attempt_id,
            "seq": row.seq,
            "event_type": row.event_type,
            "payload": loads(row.payload_json, {}),
            "created_at": row.created_at,
        }

    def _plan_row(self, plan_id: str) -> RuntimePlanRow:
        row = self.session.get(RuntimePlanRow, plan_id)
        if row is None:
            raise NotFoundError(plan_id)
        return row

    def _task_row(self, task_id: str) -> RuntimeTaskRow:
        row = self.session.get(RuntimeTaskRow, task_id)
        if row is None:
            raise NotFoundError(task_id)
        return row

    def _attempt_row(self, attempt_id: str) -> RuntimeTaskAttemptRow:
        row = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if row is None:
            raise NotFoundError(attempt_id)
        return row

    def _task_rows(self, plan_id: str) -> list[RuntimeTaskRow]:
        return list(
            self.session.scalars(
                select(RuntimeTaskRow)
                .where(RuntimeTaskRow.plan_id == plan_id)
                .order_by(
                    RuntimeTaskRow.order_index,
                    RuntimeTaskRow.id,
                )
            ).all()
        )

    def _attempt_rows(self, task_id: str) -> list[RuntimeTaskAttemptRow]:
        return list(
            self.session.scalars(
                select(RuntimeTaskAttemptRow)
                .where(RuntimeTaskAttemptRow.task_id == task_id)
                .order_by(RuntimeTaskAttemptRow.attempt)
            ).all()
        )

    def get_plan(
        self,
        plan_id: str,
        *,
        include_tasks: bool = True,
        include_attempts: bool = True,
    ) -> dict[str, Any]:
        plan = self._plan(self._plan_row(plan_id))
        if include_tasks:
            plan["tasks"] = [
                self._task(
                    row,
                    self._attempt_rows(row.id)
                    if include_attempts
                    else None,
                )
                for row in self._task_rows(plan_id)
            ]
        return plan

    def get_task(
        self,
        task_id: str,
        *,
        include_attempts: bool = True,
    ) -> dict[str, Any]:
        row = self._task_row(task_id)
        return self._task(
            row,
            self._attempt_rows(task_id) if include_attempts else None,
        )

    def get_attempt(self, attempt_id: str) -> dict[str, Any]:
        return self._attempt(self._attempt_row(attempt_id))

    def find_plan_by_idempotency(
        self,
        kind: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        row = self.session.scalar(
            select(RuntimePlanRow).where(
                RuntimePlanRow.kind == kind,
                RuntimePlanRow.idempotency_key == idempotency_key,
            )
        )
        return self.get_plan(row.id) if row else None

    def find_plan_by_subject(
        self,
        subject_type: str,
        subject_id: str,
        *,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        statement = select(RuntimePlanRow).where(
            RuntimePlanRow.subject_type == subject_type,
            RuntimePlanRow.subject_id == subject_id,
        )
        if kind:
            statement = statement.where(RuntimePlanRow.kind == kind)
        row = self.session.scalar(
            statement.order_by(
                RuntimePlanRow.created_at.desc(),
                RuntimePlanRow.id.desc(),
            )
        )
        return self.get_plan(row.id) if row else None

    def list_plans(
        self,
        project_id: str,
        *,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        statement = select(RuntimePlanRow).where(
            RuntimePlanRow.project_id == project_id
        )
        if kind:
            statement = statement.where(RuntimePlanRow.kind == kind)
        if status:
            statement = statement.where(RuntimePlanRow.status == status)
        rows = self.session.scalars(
            statement.order_by(
                RuntimePlanRow.created_at.desc(),
                RuntimePlanRow.id.desc(),
            ).limit(limit)
        ).all()
        return [self._plan(row) for row in rows]

    def create_plan(
        self,
        *,
        project_id: str,
        kind: str,
        subject_type: str = "",
        subject_id: str = "",
        idempotency_key: str | None = None,
        priority: int = 0,
        input: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "").strip()
        if not normalized_kind:
            raise ValueError("runtime plan kind is required")
        normalized_key = (
            str(idempotency_key).strip()
            if idempotency_key is not None
            else None
        )
        if normalized_key:
            existing = self.find_plan_by_idempotency(
                normalized_kind,
                normalized_key,
            )
            if existing is not None:
                return existing

        now = time.time()
        row = RuntimePlanRow(
            id=new_id(),
            project_id=project_id,
            kind=normalized_kind,
            subject_type=str(subject_type or "")[:100],
            subject_id=str(subject_id or "")[:64],
            idempotency_key=normalized_key or None,
            status="draft",
            priority=int(priority),
            event_seq=0,
            input_json=dumps(deepcopy(input or {})),
            policy_json=dumps(deepcopy(policy or {})),
            budget_json=dumps(deepcopy(budget or {})),
            usage_json="{}",
            result_json="{}",
            error="",
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        self.session.add(row)
        self.session.flush()
        self.append_event(
            row.id,
            "plan.created",
            payload={
                "kind": row.kind,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
            },
        )
        return self.get_plan(row.id)

    def add_task(
        self,
        plan_id: str,
        *,
        task_key: str,
        task_type: str,
        payload: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        depends_on_task_ids: list[str] | None = None,
        priority: int = 0,
        order_index: int | None = None,
        max_attempts: int = 1,
        timeout_seconds: float = 0.0,
        available_at: float | None = None,
    ) -> dict[str, Any]:
        plan = self._plan_row(plan_id)
        if plan.status != "draft":
            raise ConflictError(
                "runtime tasks can only be added to a draft plan"
            )
        normalized_key = str(task_key or "").strip()
        normalized_type = str(task_type or "").strip()
        if not normalized_key or not normalized_type:
            raise ValueError("runtime task key and type are required")
        dependencies = list(
            dict.fromkeys(str(item) for item in (depends_on_task_ids or []))
        )
        for dependency_id in dependencies:
            dependency = self._task_row(dependency_id)
            if dependency.plan_id != plan_id:
                raise ConflictError(
                    "runtime task dependency belongs to another plan"
                )
        if order_index is None:
            current_max = self.session.scalar(
                select(func.max(RuntimeTaskRow.order_index)).where(
                    RuntimeTaskRow.plan_id == plan_id
                )
            )
            order_index = int(current_max or -1) + 1
        now = time.time()
        row = RuntimeTaskRow(
            id=new_id(),
            plan_id=plan_id,
            project_id=plan.project_id,
            task_key=normalized_key[:160],
            task_type=normalized_type[:120],
            status="queued",
            priority=int(priority),
            order_index=int(order_index),
            depends_on_task_ids_json=dumps(dependencies),
            payload_json=dumps(deepcopy(payload or {})),
            policy_json=dumps(deepcopy(policy or {})),
            checkpoint_json="{}",
            result_json="{}",
            usage_json="{}",
            error="",
            attempt_count=0,
            max_attempts=max(1, min(int(max_attempts), 100)),
            timeout_seconds=max(0.0, float(timeout_seconds)),
            available_at=(
                now if available_at is None else float(available_at)
            ),
            cancel_requested=False,
            claim_token="",
            claim_owner="",
            claim_until=None,
            claim_attempt=0,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        self.session.add(row)
        self.session.flush()
        self.append_event(
            plan_id,
            "task.created",
            task_id=row.id,
            payload={
                "task_key": row.task_key,
                "task_type": row.task_type,
                "depends_on_task_ids": dependencies,
            },
        )
        return self.get_task(row.id)

    def set_task_dependencies(
        self,
        task_id: str,
        dependency_ids: list[str],
    ) -> dict[str, Any]:
        row = self._task_row(task_id)
        plan = self._plan_row(row.plan_id)
        if plan.status != "draft":
            raise ConflictError(
                "runtime task dependencies are frozen after queueing"
            )
        normalized = list(
            dict.fromkeys(str(item) for item in dependency_ids)
        )
        if task_id in normalized:
            raise ConflictError("runtime task cannot depend on itself")
        for dependency_id in normalized:
            dependency = self._task_row(dependency_id)
            if dependency.plan_id != row.plan_id:
                raise ConflictError(
                    "runtime task dependency belongs to another plan"
                )
        row.depends_on_task_ids_json = dumps(normalized)
        row.updated_at = time.time()
        self.session.flush()
        return self.get_task(task_id)

    def queue_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self._plan_row(plan_id)
        tasks = self._task_rows(plan_id)
        if not tasks:
            raise ConflictError("runtime plan requires at least one task")
        if plan.status == "queued":
            return self.get_plan(plan_id)
        if plan.status != "draft":
            raise ConflictError(
                f"runtime plan cannot be queued from {plan.status}"
            )
        now = time.time()
        plan.status = "queued"
        plan.error = ""
        plan.updated_at = now
        plan.completed_at = None
        self.session.flush()
        self.append_event(plan_id, "plan.queued")
        return self.get_plan(plan_id)

    def append_event(
        self,
        plan_id: str,
        event_type: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        self._plan_row(plan_id)
        now = time.time() if created_at is None else float(created_at)
        sequence = self.session.execute(
            update(RuntimePlanRow)
            .where(RuntimePlanRow.id == plan_id)
            .values(
                event_seq=RuntimePlanRow.event_seq + 1,
                updated_at=now,
            )
            .returning(RuntimePlanRow.event_seq)
            .execution_options(synchronize_session=False)
        ).scalar_one()
        row = RuntimeTaskEventRow(
            id=new_id(),
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            seq=int(sequence),
            event_type=str(event_type or "")[:120],
            payload_json=dumps(deepcopy(payload or {})),
            created_at=now,
        )
        self.session.add(row)
        self.session.flush()
        self.session.expire_all()
        return self._event(row)

    def list_events(
        self,
        plan_id: str,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self._plan_row(plan_id)
        limit = max(1, min(int(limit), 1000))
        rows = self.session.scalars(
            select(RuntimeTaskEventRow)
            .where(
                RuntimeTaskEventRow.plan_id == plan_id,
                RuntimeTaskEventRow.seq > int(after_seq),
            )
            .order_by(RuntimeTaskEventRow.seq)
            .limit(limit)
        ).all()
        return [self._event(row) for row in rows]

    def _dependency_state(
        self,
        task: RuntimeTaskRow,
    ) -> tuple[str, str]:
        dependency_ids = loads(
            task.depends_on_task_ids_json,
            [],
        )
        if not dependency_ids:
            return "ready", ""
        rows = self.session.scalars(
            select(RuntimeTaskRow).where(
                RuntimeTaskRow.id.in_(dependency_ids)
            )
        ).all()
        if len(rows) != len(set(dependency_ids)):
            return "blocked", "runtime task dependency no longer exists"
        statuses = {row.status for row in rows}
        if statuses & {"blocked", "failed", "canceled"}:
            return "blocked", "runtime task dependency cannot succeed"
        if all(
            row.status in {"skipped", "succeeded"}
            for row in rows
        ):
            return "ready", ""
        return "waiting", ""

    def claim_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        task = self._task_row(task_id)
        dependency_state, dependency_error = self._dependency_state(task)
        if dependency_state == "blocked":
            self._block_task(task.id, dependency_error)
            self.reconcile_plan(task.plan_id)
            return None
        if dependency_state != "ready":
            return None

        claimed_at = time.time() if now is None else float(now)
        lease = max(1.0, float(lease_seconds))
        token = new_id()
        owner = str(worker_id or "worker")[:160]
        active_plan_ids = select(RuntimePlanRow.id).where(
            RuntimePlanRow.status.in_(tuple(ACTIVE_PLAN_STATUSES))
        )
        changed = self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task_id,
                RuntimeTaskRow.status == "queued",
                RuntimeTaskRow.available_at <= claimed_at,
                RuntimeTaskRow.cancel_requested.is_(False),
                or_(
                    RuntimeTaskRow.claim_until.is_(None),
                    RuntimeTaskRow.claim_until <= claimed_at,
                ),
                RuntimeTaskRow.plan_id.in_(active_plan_ids),
            )
            .values(
                status="running",
                attempt_count=RuntimeTaskRow.attempt_count + 1,
                claim_token=token,
                claim_owner=owner,
                claim_until=claimed_at + lease,
                claim_attempt=RuntimeTaskRow.claim_attempt + 1,
                started_at=func.coalesce(
                    RuntimeTaskRow.started_at,
                    claimed_at,
                ),
                completed_at=None,
                error="",
                updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return None

        claimed = self._task_row(task_id)
        attempt = RuntimeTaskAttemptRow(
            id=new_id(),
            plan_id=claimed.plan_id,
            task_id=claimed.id,
            attempt=claimed.attempt_count,
            status="running",
            worker_id=owner,
            claim_token=token,
            checkpoint_json=claimed.checkpoint_json,
            result_json="{}",
            usage_json="{}",
            error="",
            retryable=False,
            started_at=claimed_at,
            heartbeat_at=claimed_at,
            lease_until=claimed_at + lease,
            completed_at=None,
        )
        self.session.add(attempt)
        self.session.execute(
            update(RuntimePlanRow)
            .where(
                RuntimePlanRow.id == claimed.plan_id,
                RuntimePlanRow.status == "queued",
            )
            .values(
                status="running",
                started_at=func.coalesce(
                    RuntimePlanRow.started_at,
                    claimed_at,
                ),
                completed_at=None,
                error="",
                updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        self.append_event(
            claimed.plan_id,
            "task.claimed",
            task_id=claimed.id,
            attempt_id=attempt.id,
            payload={
                "attempt": attempt.attempt,
                "worker_id": owner,
                "lease_until": attempt.lease_until,
            },
            created_at=claimed_at,
        )
        return {
            "plan": self.get_plan(
                claimed.plan_id,
                include_tasks=False,
            ),
            "task": self.get_task(
                claimed.id,
                include_attempts=False,
            ),
            "attempt": self.get_attempt(attempt.id),
            "claim_token": token,
        }

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: float = 60.0,
        kinds: Iterable[str] | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        claimed_at = time.time() if now is None else float(now)
        statement = (
            select(RuntimeTaskRow)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimeTaskRow.plan_id,
            )
            .where(
                RuntimeTaskRow.status == "queued",
                RuntimeTaskRow.available_at <= claimed_at,
                RuntimeTaskRow.cancel_requested.is_(False),
                or_(
                    RuntimeTaskRow.claim_until.is_(None),
                    RuntimeTaskRow.claim_until <= claimed_at,
                ),
                RuntimePlanRow.status.in_(
                    tuple(ACTIVE_PLAN_STATUSES)
                ),
            )
        )
        normalized_kinds = _normalized_statuses(kinds)
        if normalized_kinds is not None:
            if not normalized_kinds:
                return None
            statement = statement.where(
                RuntimePlanRow.kind.in_(normalized_kinds)
            )
        candidates = self.session.scalars(
            statement.order_by(
                RuntimePlanRow.priority.desc(),
                RuntimeTaskRow.priority.desc(),
                RuntimePlanRow.created_at,
                RuntimeTaskRow.order_index,
                RuntimeTaskRow.id,
            ).limit(MAX_TASK_SCAN)
        ).all()
        for candidate in candidates:
            claimed = self.claim_task(
                candidate.id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=claimed_at,
            )
            if claimed is not None:
                return claimed
        return None

    def heartbeat(
        self,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        *,
        lease_seconds: float,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        heartbeat_at = time.time() if now is None else float(now)
        lease_until = heartbeat_at + max(1.0, float(lease_seconds))
        task_values: dict[str, Any] = {
            "claim_until": lease_until,
            "updated_at": heartbeat_at,
        }
        attempt_values: dict[str, Any] = {
            "heartbeat_at": heartbeat_at,
            "lease_until": lease_until,
        }
        if checkpoint is not None:
            encoded = dumps(deepcopy(checkpoint))
            task_values["checkpoint_json"] = encoded
            attempt_values["checkpoint_json"] = encoded
        if usage is not None:
            encoded_usage = dumps(deepcopy(usage))
            task_values["usage_json"] = encoded_usage
            attempt_values["usage_json"] = encoded_usage

        task_changed = self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task_id,
                RuntimeTaskRow.status == "running",
                RuntimeTaskRow.claim_token == claim_token,
            )
            .values(**task_values)
            .execution_options(synchronize_session=False)
        )
        attempt_changed = self.session.execute(
            update(RuntimeTaskAttemptRow)
            .where(
                RuntimeTaskAttemptRow.id == attempt_id,
                RuntimeTaskAttemptRow.task_id == task_id,
                RuntimeTaskAttemptRow.status == "running",
                RuntimeTaskAttemptRow.claim_token == claim_token,
            )
            .values(**attempt_values)
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if task_changed.rowcount != 1 or attempt_changed.rowcount != 1:
            raise ConflictError("runtime task lease is no longer owned")
        return {
            "task": self.get_task(
                task_id,
                include_attempts=False,
            ),
            "attempt": self.get_attempt(attempt_id),
        }

    def complete_task(
        self,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        *,
        result: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        completed_at = time.time() if now is None else float(now)
        encoded_result = dumps(deepcopy(result or {}))
        encoded_usage = dumps(deepcopy(usage or {}))
        task_values: dict[str, Any] = {
            "status": "succeeded",
            "result_json": encoded_result,
            "usage_json": encoded_usage,
            "error": "",
            "claim_token": "",
            "claim_owner": "",
            "claim_until": None,
            "cancel_requested": False,
            "completed_at": completed_at,
            "updated_at": completed_at,
        }
        attempt_values: dict[str, Any] = {
            "status": "succeeded",
            "result_json": encoded_result,
            "usage_json": encoded_usage,
            "error": "",
            "retryable": False,
            "heartbeat_at": completed_at,
            "lease_until": completed_at,
            "completed_at": completed_at,
        }
        if checkpoint is not None:
            encoded_checkpoint = dumps(deepcopy(checkpoint))
            task_values["checkpoint_json"] = encoded_checkpoint
            attempt_values["checkpoint_json"] = encoded_checkpoint

        task = self._task_row(task_id)
        plan_id = task.plan_id
        task_changed = self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task_id,
                RuntimeTaskRow.status == "running",
                RuntimeTaskRow.claim_token == claim_token,
                RuntimeTaskRow.cancel_requested.is_(False),
            )
            .values(**task_values)
            .execution_options(synchronize_session=False)
        )
        attempt_changed = self.session.execute(
            update(RuntimeTaskAttemptRow)
            .where(
                RuntimeTaskAttemptRow.id == attempt_id,
                RuntimeTaskAttemptRow.task_id == task_id,
                RuntimeTaskAttemptRow.status == "running",
                RuntimeTaskAttemptRow.claim_token == claim_token,
            )
            .values(**attempt_values)
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if task_changed.rowcount != 1 or attempt_changed.rowcount != 1:
            raise ConflictError("runtime task completion lost its lease")
        self.append_event(
            plan_id,
            "task.succeeded",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={"result": deepcopy(result or {})},
            created_at=completed_at,
        )
        self.reconcile_plan(plan_id, now=completed_at)
        return self.get_task(task_id)

    def fail_task(
        self,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        *,
        error: str,
        retryable: bool = True,
        backoff_seconds: float = 0.0,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        failed_at = time.time() if now is None else float(now)
        task = self._task_row(task_id)
        plan = self._plan_row(task.plan_id)
        can_retry = (
            bool(retryable)
            and task.attempt_count < task.max_attempts
            and plan.status in ACTIVE_PLAN_STATUSES
            and not task.cancel_requested
        )
        task_status = "queued" if can_retry else "failed"
        task_values: dict[str, Any] = {
            "status": task_status,
            "error": str(error),
            "claim_token": "",
            "claim_owner": "",
            "claim_until": None,
            "available_at": (
                failed_at + max(0.0, float(backoff_seconds))
                if can_retry
                else task.available_at
            ),
            "completed_at": None if can_retry else failed_at,
            "updated_at": failed_at,
        }
        attempt_values: dict[str, Any] = {
            "status": "failed",
            "error": str(error),
            "retryable": can_retry,
            "heartbeat_at": failed_at,
            "lease_until": failed_at,
            "completed_at": failed_at,
        }
        if checkpoint is not None:
            encoded_checkpoint = dumps(deepcopy(checkpoint))
            task_values["checkpoint_json"] = encoded_checkpoint
            attempt_values["checkpoint_json"] = encoded_checkpoint
        if usage is not None:
            encoded_usage = dumps(deepcopy(usage))
            task_values["usage_json"] = encoded_usage
            attempt_values["usage_json"] = encoded_usage

        task_changed = self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task_id,
                RuntimeTaskRow.status == "running",
                RuntimeTaskRow.claim_token == claim_token,
            )
            .values(**task_values)
            .execution_options(synchronize_session=False)
        )
        attempt_changed = self.session.execute(
            update(RuntimeTaskAttemptRow)
            .where(
                RuntimeTaskAttemptRow.id == attempt_id,
                RuntimeTaskAttemptRow.task_id == task_id,
                RuntimeTaskAttemptRow.status == "running",
                RuntimeTaskAttemptRow.claim_token == claim_token,
            )
            .values(**attempt_values)
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if task_changed.rowcount != 1 or attempt_changed.rowcount != 1:
            raise ConflictError("runtime task failure lost its lease")
        self.append_event(
            task.plan_id,
            (
                "task.retry_scheduled"
                if can_retry
                else "task.failed"
            ),
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "error": str(error),
                "retryable": can_retry,
                "available_at": task_values["available_at"],
            },
            created_at=failed_at,
        )
        self.reconcile_plan(task.plan_id, now=failed_at)
        return self.get_task(task_id)

    def _block_task(self, task_id: str, error: str) -> None:
        now = time.time()
        self.session.execute(
            update(RuntimeTaskRow)
            .where(
                RuntimeTaskRow.id == task_id,
                RuntimeTaskRow.status == "queued",
            )
            .values(
                status="blocked",
                error=str(error),
                claim_token="",
                claim_owner="",
                claim_until=None,
                completed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()

    def cancel_plan(
        self,
        plan_id: str,
        *,
        reason: str = "runtime plan canceled",
        now: float | None = None,
    ) -> dict[str, Any]:
        canceled_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        if plan.status == "canceled":
            return self.get_plan(plan_id)
        if plan.status in {"succeeded", "failed"}:
            raise ConflictError(
                f"runtime plan is already {plan.status}"
            )
        self.session.execute(
            update(RuntimePlanRow)
            .where(
                RuntimePlanRow.id == plan_id,
                RuntimePlanRow.status.notin_(
                    tuple(TERMINAL_PLAN_STATUSES)
                ),
            )
            .values(
                status="canceled",
                error=str(reason),
                completed_at=canceled_at,
                updated_at=canceled_at,
            )
            .execution_options(synchronize_session=False)
        )
        task_ids = list(
            self.session.scalars(
                select(RuntimeTaskRow.id).where(
                    RuntimeTaskRow.plan_id == plan_id,
                    RuntimeTaskRow.status.notin_(
                        tuple(TERMINAL_TASK_STATUSES)
                    ),
                )
            ).all()
        )
        if task_ids:
            self.session.execute(
                update(RuntimeTaskRow)
                .where(RuntimeTaskRow.id.in_(task_ids))
                .values(
                    status="canceled",
                    cancel_requested=True,
                    error=str(reason),
                    claim_token="",
                    claim_owner="",
                    claim_until=None,
                    completed_at=canceled_at,
                    updated_at=canceled_at,
                )
                .execution_options(synchronize_session=False)
            )
            self.session.execute(
                update(RuntimeTaskAttemptRow)
                .where(
                    RuntimeTaskAttemptRow.task_id.in_(task_ids),
                    RuntimeTaskAttemptRow.status == "running",
                )
                .values(
                    status="canceled",
                    error=str(reason),
                    retryable=False,
                    heartbeat_at=canceled_at,
                    lease_until=canceled_at,
                    completed_at=canceled_at,
                )
                .execution_options(synchronize_session=False)
            )
        self.session.expire_all()
        self.append_event(
            plan_id,
            "plan.canceled",
            payload={"reason": str(reason)},
            created_at=canceled_at,
        )
        return self.get_plan(plan_id)

    def recover_expired(
        self,
        *,
        now: float | None = None,
        kinds: Iterable[str] | None = None,
    ) -> int:
        recovered_at = time.time() if now is None else float(now)
        statement = (
            select(RuntimeTaskRow)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimeTaskRow.plan_id,
            )
            .where(
                RuntimeTaskRow.status == "running",
                or_(
                    and_(
                        RuntimeTaskRow.claim_until.is_not(None),
                        RuntimeTaskRow.claim_until <= recovered_at,
                    ),
                    RuntimeTaskRow.timeout_seconds > 0,
                ),
                RuntimePlanRow.status.in_(
                    tuple(ACTIVE_PLAN_STATUSES)
                ),
            )
        )
        normalized_kinds = _normalized_statuses(kinds)
        if normalized_kinds is not None:
            if not normalized_kinds:
                return 0
            statement = statement.where(
                RuntimePlanRow.kind.in_(normalized_kinds)
            )
        rows = self.session.scalars(
            statement.order_by(RuntimeTaskRow.claim_until)
        ).all()
        touched_plans: set[str] = set()
        recovered = 0
        for stale in rows:
            current = self._task_row(stale.id)
            attempt = self.session.scalar(
                select(RuntimeTaskAttemptRow).where(
                    RuntimeTaskAttemptRow.task_id == current.id,
                    RuntimeTaskAttemptRow.attempt == (
                        current.attempt_count
                    ),
                    RuntimeTaskAttemptRow.status == "running",
                    RuntimeTaskAttemptRow.claim_token == (
                        current.claim_token
                    ),
                )
            )
            timed_out = bool(
                attempt is not None
                and current.timeout_seconds > 0
                and (
                    attempt.started_at + current.timeout_seconds
                    <= recovered_at
                )
            )
            lease_expired = bool(
                current.claim_until is not None
                and current.claim_until <= recovered_at
            )
            if (
                current.status != "running"
                or not (timed_out or lease_expired)
            ):
                continue
            reason = (
                "runtime task timed out"
                if timed_out
                else "runtime task lease expired"
            )
            reason_code = "timeout" if timed_out else "lease_expired"
            can_retry = (
                current.attempt_count < current.max_attempts
                and not current.cancel_requested
            )
            next_status = "queued" if can_retry else "failed"
            if attempt is not None:
                attempt.status = (
                    "timed_out" if timed_out else "interrupted"
                )
                attempt.error = reason
                attempt.retryable = can_retry
                attempt.heartbeat_at = recovered_at
                attempt.lease_until = recovered_at
                attempt.completed_at = recovered_at
            current.status = next_status
            current.error = reason
            current.claim_token = ""
            current.claim_owner = ""
            current.claim_until = None
            current.available_at = recovered_at
            current.completed_at = (
                None if can_retry else recovered_at
            )
            current.updated_at = recovered_at
            self.session.flush()
            self.append_event(
                current.plan_id,
                (
                    "task.recovered"
                    if can_retry
                    else "task.failed"
                ),
                task_id=current.id,
                attempt_id=(attempt.id if attempt else None),
                payload={
                    "attempt": current.attempt_count,
                    "retryable": can_retry,
                    "reason": reason_code,
                },
                created_at=recovered_at,
            )
            touched_plans.add(current.plan_id)
            recovered += 1

        for plan_id in touched_plans:
            self.reconcile_plan(plan_id, now=recovered_at)
        return recovered

    def reconcile_plan(
        self,
        plan_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        checked_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        if plan.status == "canceled":
            return self.get_plan(plan_id)
        tasks = self._task_rows(plan_id)
        statuses = {task.status for task in tasks}
        if not tasks:
            status = "draft"
            error = ""
        elif "failed" in statuses:
            status = "failed"
            error = "one or more runtime tasks failed"
        elif "blocked" in statuses:
            status = "blocked"
            error = "one or more runtime tasks are blocked"
        elif all(
            task.status in {"skipped", "succeeded"}
            for task in tasks
        ):
            status = "succeeded"
            error = ""
        elif "running" in statuses:
            status = "running"
            error = ""
        else:
            status = "queued"
            error = ""
        plan.status = status
        plan.error = error
        plan.updated_at = checked_at
        if status == "running" and plan.started_at is None:
            plan.started_at = checked_at
        if status in TERMINAL_PLAN_STATUSES:
            plan.completed_at = checked_at
        else:
            plan.completed_at = None
        self.session.flush()
        if status in TERMINAL_PLAN_STATUSES:
            existing = self.session.scalar(
                select(RuntimeTaskEventRow.id).where(
                    RuntimeTaskEventRow.plan_id == plan_id,
                    RuntimeTaskEventRow.event_type
                    == f"plan.{status}",
                )
            )
            if existing is None:
                self.append_event(
                    plan_id,
                    f"plan.{status}",
                    payload={"error": error},
                    created_at=checked_at,
                )
        return self.get_plan(plan_id)

    def runnable_task_ids(
        self,
        *,
        kinds: Iterable[str] | None = None,
        now: float | None = None,
        limit: int = 100,
    ) -> list[str]:
        available_at = time.time() if now is None else float(now)
        statement = (
            select(RuntimeTaskRow.id)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimeTaskRow.plan_id,
            )
            .where(
                RuntimeTaskRow.status == "queued",
                RuntimeTaskRow.available_at <= available_at,
                RuntimeTaskRow.cancel_requested.is_(False),
                RuntimePlanRow.status.in_(
                    tuple(ACTIVE_PLAN_STATUSES)
                ),
            )
        )
        normalized_kinds = _normalized_statuses(kinds)
        if normalized_kinds is not None:
            if not normalized_kinds:
                return []
            statement = statement.where(
                RuntimePlanRow.kind.in_(normalized_kinds)
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    RuntimePlanRow.priority.desc(),
                    RuntimeTaskRow.priority.desc(),
                    RuntimePlanRow.created_at,
                    RuntimeTaskRow.order_index,
                ).limit(max(1, min(int(limit), 500)))
            ).all()
        )


__all__ = [
    "ACTIVE_PLAN_STATUSES",
    "ATTEMPT_STATUSES",
    "PLAN_STATUSES",
    "TASK_STATUSES",
    "TERMINAL_PLAN_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "TaskRuntimeRepository",
]
