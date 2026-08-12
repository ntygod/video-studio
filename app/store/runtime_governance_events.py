"""Exactly-once semantic events used by runtime governance."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .repositories import ConflictError, new_id
from .runtime_control_models import RuntimeEventDedupeRow


class RuntimeGovernanceEventMixin:
    def _append_governance_event_once(
        self,
        plan_id: str,
        event_type: str,
        dedupe_key: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Persist one governance event per semantic action identity."""

        normalized_key = str(dedupe_key or "")[:240]
        existing = self.session.scalar(
            select(RuntimeEventDedupeRow).where(
                RuntimeEventDedupeRow.plan_id == plan_id,
                RuntimeEventDedupeRow.dedupe_key == normalized_key,
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
                        dedupe_key=normalized_key,
                        event_id=None,
                        created_at=marker_created_at,
                    )
                )
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimeEventDedupeRow).where(
                    RuntimeEventDedupeRow.plan_id == plan_id,
                    RuntimeEventDedupeRow.dedupe_key == normalized_key,
                )
            )
            if existing is None:
                raise
            return self._deduped_event(existing)

        event = super().append_event(
            plan_id,
            event_type,
            task_id=task_id,
            attempt_id=attempt_id,
            payload=deepcopy(payload or {}),
            created_at=created_at,
        )
        changed = self.session.execute(
            update(RuntimeEventDedupeRow)
            .where(
                RuntimeEventDedupeRow.id == marker_id,
                RuntimeEventDedupeRow.event_id.is_(None),
            )
            .values(event_id=event["id"])
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            raise ConflictError(
                "runtime governance event lost its dedupe assignment"
            )
        event["deduplicated"] = False
        return event


__all__ = ["RuntimeGovernanceEventMixin"]
