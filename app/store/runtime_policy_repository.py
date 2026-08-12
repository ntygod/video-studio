"""Durable runtime policy decisions and user approval suspension."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from .json_codec import dumps, loads
from .repositories import ConflictError, NotFoundError, new_id
from .runtime_governance_models import RuntimePolicyDecisionRow
from .task_runtime_models import (
    RuntimePlanRow,
    RuntimeTaskAttemptRow,
    RuntimeTaskRow,
)


class RuntimePolicyRepositoryMixin:
    def _decision(row: RuntimePolicyDecisionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "task_id": row.task_id,
            "action_key": row.action_key,
            "action_type": row.action_type,
            "risk_level": row.risk_level,
            "policy_version": row.policy_version,
            "status": row.status,
            "reason": row.reason,
            "context": loads(row.context_json, {}),
            "requested_by_type": row.requested_by_type,
            "requested_by_id": row.requested_by_id,
            "decided_by_type": row.decided_by_type,
            "decided_by_id": row.decided_by_id,
            "decision_note": row.decision_note,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "decided_at": row.decided_at,
        }

    def _decision_row(self, decision_id: str) -> RuntimePolicyDecisionRow:
        row = self.session.get(RuntimePolicyDecisionRow, decision_id)
        if row is None:
            raise NotFoundError(decision_id)
        return row

    def get_policy_decision(self, decision_id: str) -> dict[str, Any]:
        return self._decision(self._decision_row(decision_id))

    def list_policy_decisions(
        self,
        plan_id: str,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        self._plan_row(plan_id)
        statement = select(RuntimePolicyDecisionRow).where(
            RuntimePolicyDecisionRow.plan_id == plan_id
        )
        if status:
            statement = statement.where(
                RuntimePolicyDecisionRow.status == status
            )
        rows = self.session.scalars(
            statement.order_by(
                RuntimePolicyDecisionRow.created_at,
                RuntimePolicyDecisionRow.id,
            )
        ).all()
        return [self._decision(row) for row in rows]

    def _policy_status(
        self,
        plan: RuntimePlanRow,
        action_type: str,
        risk_level: str,
    ) -> tuple[str, str, str]:
        policy = loads(plan.policy_json, {})
        version = str(policy.get("version") or "runtime-policy@1")[:80]
        denied = {str(item) for item in policy.get("denied_actions") or []}
        allowed = {str(item) for item in policy.get("allowed_actions") or []}
        confirmations = {
            str(item)
            for item in policy.get("confirmation_risk_levels") or []
        }
        if action_type in denied:
            return "denied", "Action is denied by runtime policy.", version
        if allowed and action_type not in allowed:
            return "denied", "Action is outside the runtime allowlist.", version
        if risk_level in confirmations:
            return (
                "pending",
                "This action requires explicit user confirmation.",
                version,
            )
        return "allowed", "Action is allowed by runtime policy.", version

    def _create_or_get_decision(
        self,
        plan: RuntimePlanRow,
        task: RuntimeTaskRow,
        *,
        action_key: str,
        action_type: str,
        risk_level: str,
        context: dict[str, Any],
        requested_by_type: str,
        requested_by_id: str,
        now: float,
    ) -> RuntimePolicyDecisionRow:
        normalized_key = str(action_key or "")[:240]
        existing = self.session.scalar(
            select(RuntimePolicyDecisionRow).where(
                RuntimePolicyDecisionRow.plan_id == plan.id,
                RuntimePolicyDecisionRow.action_key == normalized_key,
            )
        )
        if existing is not None:
            if (
                existing.action_type != action_type
                or existing.risk_level != risk_level
            ):
                raise ConflictError(
                    "runtime action identity changed after policy evaluation"
                )
            return existing

        status, reason, version = self._policy_status(
            plan,
            action_type,
            risk_level,
        )
        decision_id = new_id()
        try:
            with self.session.begin_nested():
                self.session.execute(
                    insert(RuntimePolicyDecisionRow).values(
                        id=decision_id,
                        plan_id=plan.id,
                        task_id=task.id,
                        action_key=normalized_key,
                        action_type=action_type[:120],
                        risk_level=risk_level[:30],
                        policy_version=version,
                        status=status,
                        reason=reason,
                        context_json=dumps(deepcopy(context)),
                        requested_by_type=requested_by_type[:40],
                        requested_by_id=requested_by_id[:160],
                        decided_by_type=(
                            "policy" if status != "pending" else ""
                        ),
                        decided_by_id=(version if status != "pending" else ""),
                        decision_note="",
                        created_at=now,
                        updated_at=now,
                        decided_at=(now if status != "pending" else None),
                    )
                )
        except IntegrityError:
            self.session.expire_all()
            existing = self.session.scalar(
                select(RuntimePolicyDecisionRow).where(
                    RuntimePolicyDecisionRow.plan_id == plan.id,
                    RuntimePolicyDecisionRow.action_key == normalized_key,
                )
            )
            if existing is None:
                raise
            return existing
        row = self.session.get(RuntimePolicyDecisionRow, decision_id)
        if row is None:
            raise ConflictError("runtime policy decision was not persisted")
        self.append_event(
            plan.id,
            "policy.decision.created",
            task_id=task.id,
            payload={"decision": self._decision(row)},
            created_at=now,
        )
        return row

    def _suspend_for_policy(
        self,
        task: RuntimeTaskRow,
        attempt_id: str,
        claim_token: str,
        decision: RuntimePolicyDecisionRow,
        *,
        checkpoint: dict[str, Any],
        usage: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if (
            task.status != "running"
            or task.claim_token != claim_token
            or attempt is None
            or attempt.status != "running"
            or attempt.claim_token != claim_token
        ):
            raise ConflictError(
                "runtime policy suspension lost its Task lease"
            )
        encoded_checkpoint = dumps(deepcopy(checkpoint))
        encoded_usage = dumps(deepcopy(usage))
        task.status = "waiting_approval"
        task.checkpoint_json = encoded_checkpoint
        task.usage_json = encoded_usage
        task.error = decision.reason
        task.claim_token = ""
        task.claim_owner = ""
        task.claim_until = None
        task.max_attempts = min(100, int(task.max_attempts) + 1)
        task.completed_at = None
        task.updated_at = now
        attempt.status = "suspended"
        attempt.checkpoint_json = encoded_checkpoint
        attempt.usage_json = encoded_usage
        attempt.error = decision.reason
        attempt.retryable = False
        attempt.heartbeat_at = now
        attempt.lease_until = now
        attempt.completed_at = now
        plan = self._plan_row(task.plan_id)
        plan.status = "running"
        plan.completed_at = None
        plan.updated_at = now
        self.session.flush()
        event = self._append_governance_event_once(
            task.plan_id,
            "agent.approval.required",
            f"agent.approval.required:{decision.id}",
            task_id=task.id,
            attempt_id=attempt.id,
            payload={
                "turn_id": plan.subject_id,
                "type": "approval.required",
                "decision": self._decision(decision),
            },
            created_at=now,
        )
        self.append_event(
            task.plan_id,
            "task.waiting_approval",
            task_id=task.id,
            attempt_id=attempt.id,
            payload={"decision_id": decision.id},
            created_at=now,
        )
        return event

    def authorize_action(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        action_key: str,
        action_type: str,
        risk_level: str,
        context: dict[str, Any],
        checkpoint: dict[str, Any],
        usage: dict[str, Any],
        requested_by_type: str = "agent",
        requested_by_id: str = "creative-director",
        now: float | None = None,
    ) -> dict[str, Any]:
        checked_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        task = self._task_row(task_id)
        if task.plan_id != plan_id:
            raise ConflictError("runtime action Task belongs to another Plan")
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if (
            task.status != "running"
            or task.claim_token != claim_token
            or attempt is None
            or attempt.task_id != task.id
            or attempt.status != "running"
            or attempt.claim_token != claim_token
        ):
            raise ConflictError(
                "runtime action authorization lost its Task lease"
            )
        decision = self._create_or_get_decision(
            plan,
            task,
            action_key=action_key,
            action_type=action_type,
            risk_level=risk_level,
            context=context,
            requested_by_type=requested_by_type,
            requested_by_id=requested_by_id,
            now=checked_at,
        )
        event = None
        budget_state = None
        if decision.status == "pending":
            event = self._suspend_for_policy(
                task,
                attempt_id,
                claim_token,
                decision,
                checkpoint=checkpoint,
                usage=usage,
                now=checked_at,
            )
        elif decision.status in {"allowed", "approved"}:
            budget_state = self._consume_tool_budget(
                plan,
                task,
                f"tool:{action_key}",
                now=checked_at,
            )
        return {
            "decision": self._decision(decision),
            "event": event,
            "budget_state": budget_state,
        }

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
        row.status = target_status
        row.decided_by_type = str(decided_by_type or "user")[:40]
        row.decided_by_id = str(decided_by_id or "workspace")[:160]
        row.decision_note = str(note or "")
        row.updated_at = decided_at
        row.decided_at = decided_at
        task.status = "queued"
        task.available_at = decided_at
        task.error = ""
        task.completed_at = None
        task.updated_at = decided_at
        plan.status = "queued"
        plan.error = ""
        plan.completed_at = None
        plan.updated_at = decided_at
        self.session.flush()
        event = self._append_governance_event_once(
            row.plan_id,
            "agent.approval.resolved",
            f"agent.approval.resolved:{row.id}",
            task_id=row.task_id,
            payload={
                "turn_id": plan.subject_id,
                "type": "approval.resolved",
                "decision": self._decision(row),
            },
            created_at=decided_at,
        )
        self.append_event(
            row.plan_id,
            "task.resumed",
            task_id=row.task_id,
            payload={
                "decision_id": row.id,
                "decision_status": row.status,
            },
            created_at=decided_at,
        )
        return {
            "decision": self._decision(row),
            "event": event,
            "plan": self.get_plan(row.plan_id),
        }

    def cancel_plan(
        self,
        plan_id: str,
        *,
        reason: str = "runtime plan canceled",
        now: float | None = None,
    ) -> dict[str, Any]:
        canceled_at = time.time() if now is None else float(now)
        result = super().cancel_plan(
            plan_id,
            reason=reason,
            now=canceled_at,
        )
        pending = self.session.scalars(
            select(RuntimePolicyDecisionRow).where(
                RuntimePolicyDecisionRow.plan_id == plan_id,
                RuntimePolicyDecisionRow.status == "pending",
            )
        ).all()
        for decision in pending:
            decision.status = "expired"
            decision.reason = (
                "The runtime Plan ended before this approval was decided."
            )
            decision.decided_by_type = "runtime"
            decision.decided_by_id = "plan-cancel"
            decision.decision_note = str(reason)
            decision.updated_at = canceled_at
            decision.decided_at = canceled_at
        if pending:
            self.session.flush()
        return self.get_plan(plan_id) if pending else result

    def reconcile_plan(
        self,
        plan_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        checked_at = time.time() if now is None else float(now)
        result = super().reconcile_plan(plan_id, now=checked_at)
        if result["status"] in {"succeeded", "failed", "canceled"}:
            return result
        tasks = self._task_rows(plan_id)
        if any(task.status == "waiting_approval" for task in tasks):
            plan = self._plan_row(plan_id)
            plan.status = "running"
            plan.error = ""
            if plan.started_at is None:
                plan.started_at = checked_at
            plan.completed_at = None
            plan.updated_at = checked_at
            self.session.flush()
            return self.get_plan(plan_id)
        return result


__all__ = ["RuntimePolicyRepositoryMixin"]
