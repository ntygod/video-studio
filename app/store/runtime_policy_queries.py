"""Read models and expiry recovery for runtime policy decisions."""

from __future__ import annotations

import time
from typing import Any, Iterable

from sqlalchemy import or_, select, update

from .json_codec import loads
from .repositories import ConflictError
from .runtime_governance_models import RuntimePolicyDecisionRow
from .task_runtime_models import RuntimePlanRow

DEFAULT_APPROVAL_TTL_SECONDS = 86_400.0
MAX_APPROVAL_TTL_SECONDS = 604_800.0


class RuntimePolicyQueryMixin:
    """Project-scoped policy queries and deterministic approval expiry."""

    @staticmethod
    def _approval_ttl_seconds(plan: RuntimePlanRow) -> float:
        policy = loads(plan.policy_json, {})
        try:
            value = float(
                policy.get(
                    "approval_ttl_seconds",
                    DEFAULT_APPROVAL_TTL_SECONDS,
                )
            )
        except (TypeError, ValueError):
            value = DEFAULT_APPROVAL_TTL_SECONDS
        return max(1.0, min(value, MAX_APPROVAL_TTL_SECONDS))

    def _create_or_get_decision(self, plan, task, **kwargs):
        row = super()._create_or_get_decision(
            plan,
            task,
            **kwargs,
        )
        if row.status == "pending" and row.expires_at is None:
            now = float(kwargs["now"])
            row.expires_at = now + self._approval_ttl_seconds(plan)
            row.updated_at = now
            self.session.flush()
        return row

    def list_project_policy_decisions(
        self,
        project_id: str,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        statement = (
            select(RuntimePolicyDecisionRow, RuntimePlanRow)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimePolicyDecisionRow.plan_id,
            )
            .where(RuntimePlanRow.project_id == project_id)
        )
        if status:
            statement = statement.where(
                RuntimePolicyDecisionRow.status == status
            )
        if kind:
            statement = statement.where(RuntimePlanRow.kind == kind)
        rows = self.session.execute(
            statement.order_by(
                RuntimePolicyDecisionRow.created_at.desc(),
                RuntimePolicyDecisionRow.id.desc(),
            ).limit(limit)
        ).all()
        result: list[dict[str, Any]] = []
        for decision, plan in rows:
            item = self._decision(decision)
            item["plan"] = {
                "id": plan.id,
                "project_id": plan.project_id,
                "kind": plan.kind,
                "subject_type": plan.subject_type,
                "subject_id": plan.subject_id,
                "status": plan.status,
                "input": loads(plan.input_json, {}),
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
            }
            result.append(item)
        return result

    def _resume_after_policy_resolution(
        self,
        decision: RuntimePolicyDecisionRow,
        *,
        now: float,
    ) -> tuple[RuntimePlanRow, Any, bool]:
        plan = self._plan_row(decision.plan_id)
        task = self._task_row(decision.task_id)
        resumed = (
            task.status == "waiting_approval"
            and plan.status not in {"succeeded", "failed", "canceled"}
        )
        if resumed:
            task.status = "queued"
            task.available_at = now
            task.error = ""
            task.completed_at = None
            task.updated_at = now
            plan.status = "queued"
            plan.error = ""
            plan.completed_at = None
            plan.updated_at = now
            self.session.flush()
        return plan, task, resumed

    def _append_policy_resolution(
        self,
        decision: RuntimePolicyDecisionRow,
        plan: RuntimePlanRow,
        task,
        *,
        now: float,
        resumed: bool,
    ) -> dict[str, Any]:
        event = self._append_governance_event_once(
            decision.plan_id,
            "agent.approval.resolved",
            f"agent.approval.resolved:{decision.id}",
            task_id=decision.task_id,
            payload={
                "turn_id": plan.subject_id,
                "type": "approval.resolved",
                "decision": self._decision(decision),
            },
            created_at=now,
        )
        if resumed:
            self.append_event(
                decision.plan_id,
                "task.resumed",
                task_id=decision.task_id,
                payload={
                    "decision_id": decision.id,
                    "decision_status": decision.status,
                    "reason": decision.reason,
                },
                created_at=now,
            )
        return event

    def _expire_policy_decision(
        self,
        decision_id: str,
        *,
        now: float,
    ) -> bool:
        changed = self.session.execute(
            update(RuntimePolicyDecisionRow)
            .where(
                RuntimePolicyDecisionRow.id == decision_id,
                RuntimePolicyDecisionRow.status == "pending",
                RuntimePolicyDecisionRow.expires_at.is_not(None),
                RuntimePolicyDecisionRow.expires_at <= now,
            )
            .values(
                status="expired",
                reason=(
                    "Approval request expired before a user decision."
                ),
                decided_by_type="runtime",
                decided_by_id="approval-expiry-reaper",
                decision_note="approval deadline exceeded",
                updated_at=now,
                decided_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            return False
        decision = self.session.get(
            RuntimePolicyDecisionRow,
            decision_id,
        )
        if decision is None:
            return False
        plan, task, resumed = self._resume_after_policy_resolution(
            decision,
            now=now,
        )
        self._append_policy_resolution(
            decision,
            plan,
            task,
            now=now,
            resumed=resumed,
        )
        return True

    def expire_pending_policy_decisions(
        self,
        *,
        kinds: Iterable[str] | None = None,
        now: float | None = None,
        limit: int = 100,
    ) -> int:
        checked_at = time.time() if now is None else float(now)
        normalized_kinds = (
            tuple(dict.fromkeys(str(kind) for kind in kinds))
            if kinds is not None
            else None
        )
        statement = (
            select(RuntimePolicyDecisionRow.id)
            .join(
                RuntimePlanRow,
                RuntimePlanRow.id == RuntimePolicyDecisionRow.plan_id,
            )
            .where(
                RuntimePolicyDecisionRow.status == "pending",
                RuntimePolicyDecisionRow.expires_at.is_not(None),
                RuntimePolicyDecisionRow.expires_at <= checked_at,
            )
            .order_by(
                RuntimePolicyDecisionRow.expires_at,
                RuntimePolicyDecisionRow.id,
            )
            .limit(max(1, min(int(limit), 1000)))
        )
        if normalized_kinds:
            statement = statement.where(
                RuntimePlanRow.kind.in_(normalized_kinds)
            )
        decision_ids = list(self.session.scalars(statement).all())
        return sum(
            1
            for decision_id in decision_ids
            if self._expire_policy_decision(
                decision_id,
                now=checked_at,
            )
        )

    def resolve_policy_decision(
        self,
        decision_id: str,
        *,
        approved: bool,
        decided_by_type: str,
        decided_by_id: str,
        note: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        decided_at = time.time() if now is None else float(now)
        row = self._decision_row(decision_id)
        target_status = "approved" if approved else "denied"
        if row.status == target_status:
            return {
                "decision": self._decision(row),
                "event": None,
                "plan": self.get_plan(row.plan_id),
            }
        if row.status != "pending":
            raise ConflictError(
                f"runtime policy decision is already {row.status}"
            )
        task = self._task_row(row.task_id)
        plan = self._plan_row(row.plan_id)
        if (
            task.status != "waiting_approval"
            or plan.status in {"succeeded", "failed", "canceled"}
        ):
            raise ConflictError(
                "runtime approval is no longer active for this Task"
            )

        changed = self.session.execute(
            update(RuntimePolicyDecisionRow)
            .where(
                RuntimePolicyDecisionRow.id == decision_id,
                RuntimePolicyDecisionRow.status == "pending",
                or_(
                    RuntimePolicyDecisionRow.expires_at.is_(None),
                    RuntimePolicyDecisionRow.expires_at > decided_at,
                ),
            )
            .values(
                status=target_status,
                decided_by_type=str(decided_by_type or "user")[:40],
                decided_by_id=str(decided_by_id or "workspace")[:160],
                decision_note=str(note or ""),
                updated_at=decided_at,
                decided_at=decided_at,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()
        if changed.rowcount != 1:
            self._expire_policy_decision(
                decision_id,
                now=decided_at,
            )
            current = self._decision_row(decision_id)
            if current.status in {target_status, "expired"}:
                return {
                    "decision": self._decision(current),
                    "event": None,
                    "plan": self.get_plan(current.plan_id),
                }
            raise ConflictError(
                f"runtime policy decision is already {current.status}"
            )

        resolved = self._decision_row(decision_id)
        plan, task, resumed = self._resume_after_policy_resolution(
            resolved,
            now=decided_at,
        )
        event = self._append_policy_resolution(
            resolved,
            plan,
            task,
            now=decided_at,
            resumed=resumed,
        )
        return {
            "decision": self._decision(resolved),
            "event": event,
            "plan": self.get_plan(resolved.plan_id),
        }


__all__ = [
    "DEFAULT_APPROVAL_TTL_SECONDS",
    "MAX_APPROVAL_TTL_SECONDS",
    "RuntimePolicyQueryMixin",
]
