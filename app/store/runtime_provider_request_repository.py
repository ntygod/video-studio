"""Durable Provider request intent, replay, and outcome reconciliation."""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .json_codec import dumps, loads
from .repositories import ConflictError, NotFoundError, new_id
from .runtime_cost_models import RuntimeCostEntryRow
from .runtime_governance_models import RuntimeBudgetTaskUsageRow
from .runtime_provider_request_models import RuntimeProviderRequestRow
from .task_runtime_models import RuntimeTaskAttemptRow, RuntimeTaskRow

_ACTIVE_STATUSES = frozenset({"dispatching", "response_started"})
_RESOLUTIONS = frozenset(
    {
        "not_sent",
        "completed_external",
        "failed_external",
        "duplicate_risk_accepted",
    }
)


def _stable_idempotency_key(plan_id: str, request_key: str) -> str:
    digest = hashlib.sha256(
        f"{plan_id}\0{request_key}".encode("utf-8")
    ).hexdigest()
    return "video-studio-" + digest[:48]


class RuntimeProviderRequestRepositoryMixin:
    @staticmethod
    def _provider_request(row: RuntimeProviderRequestRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "task_id": row.task_id,
            "attempt_id": row.attempt_id,
            "request_key": row.request_key,
            "source_type": row.source_type,
            "status": row.status,
            "provider_profile_id": row.provider_profile_id,
            "provider_name": row.provider_name,
            "adapter": row.adapter,
            "model_profile_id": row.model_profile_id,
            "model_id": row.model_id,
            "capability_type": row.capability_type,
            "request_sha256": row.request_sha256,
            "request_summary": loads(row.request_summary_json, {}),
            "idempotency_key": row.idempotency_key,
            "idempotency_header": row.idempotency_header,
            "idempotency_supported": bool(row.idempotency_header),
            "provider_request_id": row.provider_request_id,
            "response": loads(row.response_json, {}),
            "usage": loads(row.usage_json, {}),
            "cost_entry_id": row.cost_entry_id,
            "dispatch_count": row.dispatch_count,
            "error": row.error,
            "resolution": row.resolution,
            "resolution_note": row.resolution_note,
            "resolved_by_type": row.resolved_by_type,
            "resolved_by_id": row.resolved_by_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "dispatched_at": row.dispatched_at,
            "response_started_at": row.response_started_at,
            "completed_at": row.completed_at,
            "failed_at": row.failed_at,
            "resolved_at": row.resolved_at,
        }

    def _provider_request_row(
        self,
        request_id: str,
    ) -> RuntimeProviderRequestRow:
        row = self.session.get(RuntimeProviderRequestRow, request_id)
        if row is None:
            raise NotFoundError(request_id)
        return row

    def get_provider_request(self, request_id: str) -> dict[str, Any]:
        return self._provider_request(self._provider_request_row(request_id))

    def list_provider_requests(
        self,
        plan_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._plan_row(plan_id)
        statement = select(RuntimeProviderRequestRow).where(
            RuntimeProviderRequestRow.plan_id == plan_id
        )
        if status:
            statement = statement.where(
                RuntimeProviderRequestRow.status == str(status)
            )
        rows = self.session.scalars(
            statement.order_by(
                RuntimeProviderRequestRow.created_at.desc(),
                RuntimeProviderRequestRow.id.desc(),
            ).limit(max(1, min(int(limit), 500)))
        ).all()
        return [self._provider_request(row) for row in rows]

    def _provider_request_lease(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        now: float,
    ):
        plan = self._plan_row(plan_id)
        task = self._task_row(task_id)
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if (
            task.plan_id != plan_id
            or task.status != "running"
            or task.claim_token != claim_token
            or task.claim_until is None
            or task.claim_until <= now
            or attempt is None
            or attempt.plan_id != plan_id
            or attempt.task_id != task_id
            or attempt.status != "running"
            or attempt.claim_token != claim_token
            or attempt.lease_until <= now
        ):
            raise ConflictError(
                "runtime Provider request lost its Task lease"
            )
        return plan, task, attempt

    @staticmethod
    def _provider_identity(snapshot: dict[str, Any]) -> tuple[str, str]:
        return (
            str(snapshot.get("provider_profile_id") or ""),
            str(snapshot.get("model_id") or ""),
        )

    def _assert_request_identity(
        self,
        row: RuntimeProviderRequestRow,
        *,
        task_id: str,
        source_type: str,
        request_sha256: str,
        provider_snapshot: dict[str, Any],
    ) -> None:
        expected_provider, expected_model = self._provider_identity(
            provider_snapshot
        )
        if (
            row.task_id != task_id
            or row.source_type != source_type
            or row.request_sha256 != request_sha256
            or row.provider_profile_id != expected_provider
            or row.model_id != expected_model
        ):
            raise ConflictError(
                "runtime Provider request identity changed during replay"
            )

    def prepare_provider_request(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        request_key: str,
        source_type: str,
        provider_snapshot: dict[str, Any],
        request_sha256: str,
        request_summary: dict[str, Any],
        idempotency_header: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        prepared_at = time.time() if now is None else float(now)
        self._provider_request_lease(
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            claim_token=claim_token,
            now=prepared_at,
        )
        normalized_key = str(request_key or "").strip()[:240]
        normalized_source = str(source_type or "provider").strip()[:80]
        normalized_sha = str(request_sha256 or "").strip().lower()
        if not normalized_key:
            raise ValueError("runtime Provider request key is required")
        if len(normalized_sha) != 64:
            raise ValueError("runtime Provider request SHA-256 is required")
        snapshot = deepcopy(provider_snapshot or {})
        existing = self.session.scalar(
            select(RuntimeProviderRequestRow).where(
                RuntimeProviderRequestRow.plan_id == plan_id,
                RuntimeProviderRequestRow.request_key == normalized_key,
            )
        )
        if existing is not None:
            self._assert_request_identity(
                existing,
                task_id=task_id,
                source_type=normalized_source,
                request_sha256=normalized_sha,
                provider_snapshot=snapshot,
            )
            if existing.status != "completed":
                existing.attempt_id = attempt_id
                existing.updated_at = prepared_at
                self.session.flush()
            return self._provider_request(existing)

        provider_id, model_id = self._provider_identity(snapshot)
        row_id = new_id()
        values = {
            "id": row_id,
            "plan_id": plan_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "request_key": normalized_key,
            "source_type": normalized_source,
            "status": "prepared",
            "provider_profile_id": provider_id[:64],
            "provider_name": str(snapshot.get("provider_name") or "")[:200],
            "adapter": str(snapshot.get("adapter") or "")[:100],
            "model_profile_id": str(
                snapshot.get("model_profile_id") or ""
            )[:64],
            "model_id": model_id[:300],
            "capability_type": str(
                snapshot.get("capability_type") or ""
            )[:50],
            "request_sha256": normalized_sha,
            "request_summary_json": dumps(deepcopy(request_summary or {})),
            "idempotency_key": _stable_idempotency_key(
                plan_id,
                normalized_key,
            ),
            "idempotency_header": str(idempotency_header or "")[:100],
            "provider_request_id": "",
            "response_json": "{}",
            "usage_json": "{}",
            "cost_entry_id": None,
            "dispatch_count": 0,
            "error": "",
            "resolution": "",
            "resolution_note": "",
            "resolved_by_type": "",
            "resolved_by_id": "",
            "created_at": prepared_at,
            "updated_at": prepared_at,
            "dispatched_at": None,
            "response_started_at": None,
            "completed_at": None,
            "failed_at": None,
            "resolved_at": None,
        }
        try:
            with self.session.begin_nested():
                self.session.add(RuntimeProviderRequestRow(**values))
                self.session.flush()
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimeProviderRequestRow).where(
                    RuntimeProviderRequestRow.plan_id == plan_id,
                    RuntimeProviderRequestRow.request_key == normalized_key,
                )
            )
            if existing is None:
                raise
            self._assert_request_identity(
                existing,
                task_id=task_id,
                source_type=normalized_source,
                request_sha256=normalized_sha,
                provider_snapshot=snapshot,
            )
            return self._provider_request(existing)

        self.session.expire_all()
        row = self._provider_request_row(row_id)
        self._append_governance_event_once(
            plan_id,
            "provider.request.prepared",
            f"provider.request.prepared:{row_id}",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "request_id": row_id,
                "request_key": normalized_key,
                "source_type": normalized_source,
                "provider_profile_id": row.provider_profile_id,
                "model_id": row.model_id,
                "request_sha256": normalized_sha,
                "idempotency_supported": bool(row.idempotency_header),
            },
            created_at=prepared_at,
        )
        return self._provider_request(row)

    @staticmethod
    def _unknown_violation(row: RuntimeProviderRequestRow) -> dict[str, Any]:
        return {
            "dimension": "provider_request_outcome_unknown",
            "code": "provider_request_outcome_unknown",
            "limit": 0,
            "actual": 1,
            "request_id": row.id,
            "request_key": row.request_key,
            "provider_profile_id": row.provider_profile_id,
            "provider_name": row.provider_name,
            "model_id": row.model_id,
            "idempotency_supported": bool(row.idempotency_header),
            "message": (
                "Provider request outcome is unknown and the channel has no "
                "configured idempotency header; automatic replay was blocked."
            ),
        }

    @staticmethod
    def _failed_violation(row: RuntimeProviderRequestRow) -> dict[str, Any]:
        return {
            "dimension": "provider_request_failed",
            "code": "provider_request_failed",
            "limit": 0,
            "actual": 1,
            "request_id": row.id,
            "request_key": row.request_key,
            "provider_profile_id": row.provider_profile_id,
            "provider_name": row.provider_name,
            "model_id": row.model_id,
            "message": row.error or "Provider request failed",
        }

    def start_provider_request(
        self,
        request_id: str,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        started_at = time.time() if now is None else float(now)
        self._provider_request_lease(
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            claim_token=claim_token,
            now=started_at,
        )
        row = self._provider_request_row(request_id)
        if row.plan_id != plan_id or row.task_id != task_id:
            raise ConflictError(
                "runtime Provider request belongs to another Task"
            )
        if row.status == "completed":
            return {
                "request": self._provider_request(row),
                "replay": True,
                "violation": None,
            }
        if row.status in _ACTIVE_STATUSES | {"outcome_unknown"}:
            if not row.idempotency_header:
                if row.status != "outcome_unknown":
                    row.status = "outcome_unknown"
                    row.error = (
                        "Provider request dispatch was interrupted before "
                        "durable completion"
                    )
                    row.failed_at = started_at
                    row.updated_at = started_at
                    self.session.flush()
                violation = self._unknown_violation(row)
                self._append_governance_event_once(
                    plan_id,
                    "provider.request.outcome_unknown",
                    f"provider.request.outcome_unknown:{row.id}",
                    task_id=task_id,
                    attempt_id=attempt_id,
                    payload={
                        "request": self._provider_request(row),
                        "violation": violation,
                    },
                    created_at=started_at,
                )
                return {
                    "request": self._provider_request(row),
                    "replay": False,
                    "violation": violation,
                }
        elif row.status == "failed":
            violation = self._failed_violation(row)
            return {
                "request": self._provider_request(row),
                "replay": False,
                "violation": violation,
            }
        elif row.status == "resolved":
            raise ConflictError(
                "runtime Provider request was manually resolved"
            )
        elif row.status != "prepared":
            raise ConflictError(
                f"runtime Provider request cannot dispatch from {row.status}"
            )

        row.status = "dispatching"
        row.attempt_id = attempt_id
        row.dispatch_count += 1
        row.dispatched_at = row.dispatched_at or started_at
        row.response_started_at = None
        row.error = ""
        row.updated_at = started_at
        self.session.flush()
        self.append_event(
            plan_id,
            "provider.request.dispatching",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "request_id": row.id,
                "dispatch_count": row.dispatch_count,
                "idempotency_key": row.idempotency_key,
                "idempotency_header": row.idempotency_header,
            },
            created_at=started_at,
        )
        return {
            "request": self._provider_request(row),
            "replay": False,
            "violation": None,
        }

    def mark_provider_request_response_started(
        self,
        request_id: str,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        observed_at = time.time() if now is None else float(now)
        self._provider_request_lease(
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            claim_token=claim_token,
            now=observed_at,
        )
        row = self._provider_request_row(request_id)
        if row.status in {"response_started", "completed"}:
            return self._provider_request(row)
        if row.status != "dispatching":
            raise ConflictError(
                f"runtime Provider response cannot start from {row.status}"
            )
        row.status = "response_started"
        row.response_started_at = observed_at
        row.updated_at = observed_at
        self.session.flush()
        self._append_governance_event_once(
            plan_id,
            "provider.request.response_started",
            (
                f"provider.request.response_started:{row.id}:"
                f"{row.dispatch_count}"
            ),
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "request_id": row.id,
                "dispatch_count": row.dispatch_count,
            },
            created_at=observed_at,
        )
        return self._provider_request(row)

    def complete_provider_request(
        self,
        request_id: str,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        provider_request_id: str,
        response: dict[str, Any],
        usage: dict[str, Any],
        cost_entry_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        completed_at = time.time() if now is None else float(now)
        self._provider_request_lease(
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            claim_token=claim_token,
            now=completed_at,
        )
        row = self._provider_request_row(request_id)
        if row.status == "completed":
            return self._provider_request(row)
        if row.status not in _ACTIVE_STATUSES | {"outcome_unknown"}:
            raise ConflictError(
                f"runtime Provider request cannot complete from {row.status}"
            )
        row.status = "completed"
        row.attempt_id = attempt_id
        row.provider_request_id = str(provider_request_id or "")[:300]
        row.response_json = dumps(deepcopy(response or {}))
        row.usage_json = dumps(deepcopy(usage or {}))
        row.cost_entry_id = str(cost_entry_id or "")[:64] or None
        row.error = ""
        row.completed_at = completed_at
        row.updated_at = completed_at
        self.session.flush()
        self._append_governance_event_once(
            plan_id,
            "provider.request.completed",
            f"provider.request.completed:{row.id}",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "request_id": row.id,
                "provider_request_id": row.provider_request_id,
                "cost_entry_id": row.cost_entry_id,
                "dispatch_count": row.dispatch_count,
            },
            created_at=completed_at,
        )
        return self._provider_request(row)

    def fail_provider_request(
        self,
        request_id: str,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        error: str,
        outcome_unknown: bool,
        provider_request_id: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        failed_at = time.time() if now is None else float(now)
        self._provider_request_lease(
            plan_id=plan_id,
            task_id=task_id,
            attempt_id=attempt_id,
            claim_token=claim_token,
            now=failed_at,
        )
        row = self._provider_request_row(request_id)
        if row.status == "completed":
            return {
                "request": self._provider_request(row),
                "violation": None,
            }
        row.status = "outcome_unknown" if outcome_unknown else "failed"
        row.attempt_id = attempt_id
        if provider_request_id:
            row.provider_request_id = str(provider_request_id)[:300]
        row.error = str(error)[:8000]
        row.failed_at = failed_at
        row.updated_at = failed_at
        self.session.flush()
        violation = (
            self._unknown_violation(row)
            if outcome_unknown
            else self._failed_violation(row)
        )
        event_type = (
            "provider.request.outcome_unknown"
            if outcome_unknown
            else "provider.request.failed"
        )
        self._append_governance_event_once(
            plan_id,
            event_type,
            f"{event_type}:{row.id}:{row.dispatch_count}",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "request": self._provider_request(row),
                "violation": violation,
            },
            created_at=failed_at,
        )
        return {
            "request": self._provider_request(row),
            "violation": violation,
        }

    def replay_provider_request(self, request_id: str) -> dict[str, Any]:
        row = self._provider_request_row(request_id)
        if row.status != "completed":
            raise ConflictError(
                "runtime Provider request has no completed response to replay"
            )
        task = self._task_row(row.task_id)
        task_usage_row = self.session.scalar(
            select(RuntimeBudgetTaskUsageRow).where(
                RuntimeBudgetTaskUsageRow.task_id == row.task_id
            )
        )
        task_usage = loads(task.usage_json, {})
        if task_usage_row is not None:
            task_usage.update(
                {
                    "prompt_tokens": int(task_usage_row.prompt_tokens),
                    "completion_tokens": int(
                        task_usage_row.completion_tokens
                    ),
                    "cost_microunits": int(
                        task_usage_row.cost_microunits
                    ),
                }
            )
        cost_entry = (
            self.session.get(RuntimeCostEntryRow, row.cost_entry_id)
            if row.cost_entry_id
            else None
        )
        return {
            "request": self._provider_request(row),
            "task_usage": task_usage,
            "cost_entry": (
                self._cost_entry(cost_entry)
                if cost_entry is not None
                else None
            ),
            "budget_state": self.budget_state(row.plan_id),
        }

    def recover_stale_provider_requests(
        self,
        *,
        now: float | None = None,
        kinds: Iterable[str] | None = None,
    ) -> int:
        recovered_at = time.time() if now is None else float(now)
        statement = select(RuntimeProviderRequestRow).where(
            RuntimeProviderRequestRow.status.in_(tuple(_ACTIVE_STATUSES))
        )
        normalized_kinds = tuple(str(item) for item in kinds) if kinds else None
        rows = list(self.session.scalars(statement).all())
        recovered = 0
        for row in rows:
            plan = self._plan_row(row.plan_id)
            if normalized_kinds is not None and plan.kind not in normalized_kinds:
                continue
            task = self.session.get(RuntimeTaskRow, row.task_id)
            attempt = (
                self.session.get(RuntimeTaskAttemptRow, row.attempt_id)
                if row.attempt_id
                else None
            )
            still_owned = bool(
                task is not None
                and task.status == "running"
                and attempt is not None
                and attempt.status == "running"
                and attempt.lease_until > recovered_at
                and task.claim_token
                and task.claim_token == attempt.claim_token
            )
            if still_owned:
                continue
            row.status = "outcome_unknown"
            row.error = (
                "Provider request dispatch was interrupted before durable "
                "completion"
            )
            row.failed_at = recovered_at
            row.updated_at = recovered_at
            self.session.flush()
            violation = self._unknown_violation(row)
            self._append_governance_event_once(
                row.plan_id,
                "provider.request.outcome_unknown",
                f"provider.request.outcome_unknown:{row.id}",
                task_id=row.task_id,
                attempt_id=row.attempt_id,
                payload={
                    "request": self._provider_request(row),
                    "violation": violation,
                    "recovered": True,
                },
                created_at=recovered_at,
            )
            recovered += 1
        return recovered

    def resolve_provider_request(
        self,
        request_id: str,
        *,
        resolution: str,
        note: str = "",
        provider_request_id: str = "",
        resolved_by_type: str = "user",
        resolved_by_id: str = "workspace-user",
        now: float | None = None,
    ) -> dict[str, Any]:
        resolved_at = time.time() if now is None else float(now)
        normalized = str(resolution or "").strip()
        if normalized not in _RESOLUTIONS:
            raise ValueError("unsupported Provider request resolution")
        row = self._provider_request_row(request_id)
        if row.status == "resolved":
            if row.resolution != normalized:
                raise ConflictError(
                    "runtime Provider request has another resolution"
                )
            return self._provider_request(row)
        if row.status not in {"outcome_unknown", "failed"}:
            raise ConflictError(
                f"runtime Provider request cannot be resolved from {row.status}"
            )
        row.status = "resolved"
        row.resolution = normalized
        row.resolution_note = str(note or "")[:8000]
        row.resolved_by_type = str(resolved_by_type or "user")[:40]
        row.resolved_by_id = str(resolved_by_id or "workspace-user")[:160]
        if provider_request_id:
            row.provider_request_id = str(provider_request_id)[:300]
        row.resolved_at = resolved_at
        row.updated_at = resolved_at
        self.session.flush()
        self._append_governance_event_once(
            row.plan_id,
            "provider.request.resolved",
            f"provider.request.resolved:{row.id}",
            task_id=row.task_id,
            attempt_id=row.attempt_id,
            payload={
                "request_id": row.id,
                "resolution": normalized,
                "note": row.resolution_note,
                "provider_request_id": row.provider_request_id,
                "resolved_by_type": row.resolved_by_type,
                "resolved_by_id": row.resolved_by_id,
            },
            created_at=resolved_at,
        )
        return self._provider_request(row)


__all__ = ["RuntimeProviderRequestRepositoryMixin"]
