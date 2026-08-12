"""Runtime repository extensions for admission control and event identity."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .repositories import ConflictError, new_id
from .runtime_control_models import (
    RuntimeAdmissionBucketRow,
    RuntimeAdmissionReservationRow,
    RuntimeEventDedupeRow,
)
from .task_runtime_models import RuntimeTaskEventRow
from .task_runtime_repository import TaskRuntimeRepository

AGENT_PLAN_KIND = "agent.turn"
DEFAULT_ADMISSION_CAPACITIES = {AGENT_PLAN_KIND: 10}
ADMISSION_RELEASE_STATUSES = frozenset(
    {"blocked", "succeeded", "failed", "canceled"}
)


class RuntimeAdmissionFull(RuntimeError):
    """A durable Plan kind has no free database-backed admission slot."""

    def __init__(
        self,
        key: str,
        capacity: int,
        active_count: int,
    ):
        self.key = key
        self.capacity = int(capacity)
        self.active_count = int(active_count)
        super().__init__(
            f"runtime admission is full for {key}: "
            f"{active_count}/{capacity} active"
        )


def _agent_event_dedupe_key(
    event_type: str,
    payload: dict[str, Any],
) -> str | None:
    """Return the stable semantic identity for replayable Agent events."""

    normalized = str(event_type or "")
    turn_id = str(payload.get("turn_id") or "")
    if normalized in {"agent.step.start", "agent.step.done"}:
        step_id = str(payload.get("step_id") or "")
        return f"{normalized}:{step_id}" if step_id else None
    if normalized == "agent.entity":
        entity = payload.get("entity") or {}
        entity_type = str(entity.get("type") or "")
        entity_id = str(entity.get("id") or "")
        if entity_type and entity_id:
            return f"{normalized}:{entity_type}:{entity_id}"
        return None
    if normalized == "agent.proposal":
        proposal = payload.get("proposal") or {}
        proposal_id = str(proposal.get("id") or "")
        return f"{normalized}:{proposal_id}" if proposal_id else None
    if normalized in {"agent.message", "agent.done"}:
        return f"{normalized}:{turn_id or 'plan'}"
    return None


class ControlledTaskRuntimeRepository(TaskRuntimeRepository):
    """Adds durable capacity reservations and semantic event deduplication."""

    def _ensure_admission_bucket(
        self,
        key: str,
        capacity: int | None = None,
    ) -> RuntimeAdmissionBucketRow | None:
        normalized = str(key or "").strip()[:160]
        if not normalized:
            raise ValueError("runtime admission key is required")
        row = self.session.get(RuntimeAdmissionBucketRow, normalized)
        if row is None and capacity is None:
            return None
        normalized_capacity = (
            max(1, min(int(capacity), 10000))
            if capacity is not None
            else None
        )
        if row is None:
            now = time.time()
            try:
                with self.session.begin_nested():
                    self.session.execute(
                        insert(RuntimeAdmissionBucketRow).values(
                            key=normalized,
                            capacity=normalized_capacity,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            except IntegrityError:
                self.session.expire_all()
            row = self.session.get(RuntimeAdmissionBucketRow, normalized)
            if row is None:
                raise ConflictError(
                    f"runtime admission bucket could not be created: {normalized}"
                )
        if (
            normalized_capacity is not None
            and row.capacity != normalized_capacity
        ):
            active_count = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(RuntimeAdmissionReservationRow)
                    .where(
                        RuntimeAdmissionReservationRow.bucket_key
                        == normalized,
                        RuntimeAdmissionReservationRow.released_at.is_(None),
                    )
                )
                or 0
            )
            if normalized_capacity < active_count:
                raise ConflictError(
                    "runtime admission capacity cannot be lower than "
                    f"active reservations: {active_count}"
                )
            row.capacity = normalized_capacity
            row.updated_at = time.time()
            self.session.flush()
        return row

    def configure_admission(
        self,
        key: str,
        capacity: int,
    ) -> dict[str, Any]:
        row = self._ensure_admission_bucket(key, capacity)
        assert row is not None
        return self.admission_state(row.key)

    def admission_state(self, key: str) -> dict[str, Any]:
        normalized = str(key or "").strip()[:160]
        row = self.session.get(RuntimeAdmissionBucketRow, normalized)
        if row is None:
            raise ConflictError(
                f"runtime admission bucket does not exist: {normalized}"
            )
        active_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(RuntimeAdmissionReservationRow)
                .where(
                    RuntimeAdmissionReservationRow.bucket_key == normalized,
                    RuntimeAdmissionReservationRow.released_at.is_(None),
                )
            )
            or 0
        )
        return {
            "key": row.key,
            "capacity": row.capacity,
            "active_count": active_count,
            "available_count": max(0, row.capacity - active_count),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _bucket_for_plan(self, plan) -> RuntimeAdmissionBucketRow | None:
        existing = self.session.get(RuntimeAdmissionBucketRow, plan.kind)
        if existing is not None:
            return existing
        default_capacity = DEFAULT_ADMISSION_CAPACITIES.get(plan.kind)
        if default_capacity is None:
            return None
        return self._ensure_admission_bucket(
            plan.kind,
            default_capacity,
        )

    def _acquire_admission(
        self,
        plan_id: str,
        bucket: RuntimeAdmissionBucketRow,
    ) -> RuntimeAdmissionReservationRow:
        existing = self.session.get(
            RuntimeAdmissionReservationRow,
            plan_id,
        )
        if existing is not None:
            if existing.released_at is None:
                return existing
            raise ConflictError(
                "runtime plan admission was already released"
            )

        acquired_at = time.time()
        capacity = max(1, int(bucket.capacity))
        for slot in range(capacity):
            try:
                with self.session.begin_nested():
                    self.session.execute(
                        insert(RuntimeAdmissionReservationRow).values(
                            plan_id=plan_id,
                            bucket_key=bucket.key,
                            slot=slot,
                            acquired_at=acquired_at,
                            released_at=None,
                        )
                    )
            except IntegrityError:
                self.session.expire_all()
                existing = self.session.get(
                    RuntimeAdmissionReservationRow,
                    plan_id,
                )
                if existing is not None and existing.released_at is None:
                    return existing
                continue
            self.session.expire_all()
            reservation = self.session.get(
                RuntimeAdmissionReservationRow,
                plan_id,
            )
            if reservation is None:
                raise ConflictError(
                    "runtime admission reservation was not persisted"
                )
            super().append_event(
                plan_id,
                "plan.admission_acquired",
                payload={
                    "bucket_key": bucket.key,
                    "slot": slot,
                    "capacity": capacity,
                },
                created_at=acquired_at,
            )
            return reservation

        state = self.admission_state(bucket.key)
        raise RuntimeAdmissionFull(
            bucket.key,
            state["capacity"],
            state["active_count"],
        )

    def _release_admission(
        self,
        plan_id: str,
        *,
        released_at: float | None = None,
    ) -> bool:
        now = time.time() if released_at is None else float(released_at)
        reservation = self.session.get(
            RuntimeAdmissionReservationRow,
            plan_id,
        )
        if reservation is None or reservation.released_at is not None:
            return False
        changed = self.session.execute(
            update(RuntimeAdmissionReservationRow)
            .where(
                RuntimeAdmissionReservationRow.plan_id == plan_id,
                RuntimeAdmissionReservationRow.released_at.is_(None),
            )
            .values(released_at=now)
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return False
        super().append_event(
            plan_id,
            "plan.admission_released",
            payload={
                "bucket_key": reservation.bucket_key,
                "slot": reservation.slot,
            },
            created_at=now,
        )
        return True

    def queue_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self._plan_row(plan_id)
        if plan.status in {"draft", "queued"}:
            bucket = self._bucket_for_plan(plan)
            if bucket is not None:
                self._acquire_admission(plan_id, bucket)
        return super().queue_plan(plan_id)

    def cancel_plan(
        self,
        plan_id: str,
        *,
        reason: str = "runtime plan canceled",
        now: float | None = None,
    ) -> dict[str, Any]:
        result = super().cancel_plan(
            plan_id,
            reason=reason,
            now=now,
        )
        self._release_admission(plan_id, released_at=now)
        return result

    def reconcile_plan(
        self,
        plan_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        result = super().reconcile_plan(plan_id, now=now)
        if result["status"] in ADMISSION_RELEASE_STATUSES:
            self._release_admission(plan_id, released_at=now)
        return result

    def _deduped_event(self, marker: RuntimeEventDedupeRow) -> dict[str, Any]:
        if not marker.event_id:
            raise ConflictError(
                "runtime event dedupe marker has no event"
            )
        row = self.session.get(RuntimeTaskEventRow, marker.event_id)
        if row is None:
            raise ConflictError(
                "runtime event dedupe marker points to a missing event"
            )
        result = self._event(row)
        result["deduplicated"] = True
        return result

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
        copied_payload = deepcopy(payload or {})
        dedupe_key = _agent_event_dedupe_key(
            event_type,
            copied_payload,
        )
        if dedupe_key is None:
            return super().append_event(
                plan_id,
                event_type,
                task_id=task_id,
                attempt_id=attempt_id,
                payload=copied_payload,
                created_at=created_at,
            )

        dedupe_key = dedupe_key[:240]
        existing = self.session.scalar(
            select(RuntimeEventDedupeRow).where(
                RuntimeEventDedupeRow.plan_id == plan_id,
                RuntimeEventDedupeRow.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            return self._deduped_event(existing)

        marker_id = new_id()
        marker_created_at = (
            time.time() if created_at is None else float(created_at)
        )
        try:
            with self.session.begin_nested():
                self.session.execute(
                    insert(RuntimeEventDedupeRow).values(
                        id=marker_id,
                        plan_id=plan_id,
                        dedupe_key=dedupe_key[:240],
                        event_id=None,
                        created_at=marker_created_at,
                    )
                )
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimeEventDedupeRow).where(
                    RuntimeEventDedupeRow.plan_id == plan_id,
                    RuntimeEventDedupeRow.dedupe_key == dedupe_key,
                )
            )
            if existing is None:
                raise
            return self._deduped_event(existing)

        result = super().append_event(
            plan_id,
            event_type,
            task_id=task_id,
            attempt_id=attempt_id,
            payload=copied_payload,
            created_at=created_at,
        )
        changed = self.session.execute(
            update(RuntimeEventDedupeRow)
            .where(
                RuntimeEventDedupeRow.id == marker_id,
                RuntimeEventDedupeRow.event_id.is_(None),
            )
            .values(event_id=result["id"])
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            raise ConflictError(
                "runtime event dedupe marker lost its event assignment"
            )
        result["deduplicated"] = False
        return result


__all__ = [
    "AGENT_PLAN_KIND",
    "ControlledTaskRuntimeRepository",
    "RuntimeAdmissionFull",
]
