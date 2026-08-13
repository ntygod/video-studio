"""Durable enforcement events for project Provider cost policy."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any

from .json_codec import loads
from .repositories import ConflictError
from .task_runtime_models import RuntimeTaskAttemptRow


class RuntimeCostPolicyRepositoryMixin:
    @staticmethod
    def _unpriced_provider_mode(plan) -> str:
        policy = loads(plan.policy_json, {})
        provider_policy = policy.get("provider_cost_policy") or {}
        if not isinstance(provider_policy, dict):
            return "allow"
        return str(
            provider_policy.get("unpriced_provider_mode") or "allow"
        )

    def record_unpriced_provider_violation(
        self,
        *,
        plan_id: str,
        task_id: str,
        attempt_id: str,
        claim_token: str,
        phase: str,
        provider_snapshot: dict[str, Any],
        cost_entry_id: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Record one strict-policy failure while the caller owns the lease."""

        checked_at = time.time() if now is None else float(now)
        plan = self._plan_row(plan_id)
        task = self._task_row(task_id)
        attempt = self.session.get(RuntimeTaskAttemptRow, attempt_id)
        if self._unpriced_provider_mode(plan) != "block":
            raise ConflictError(
                "runtime Plan does not require priced Provider usage"
            )
        if (
            task.plan_id != plan_id
            or task.status != "running"
            or task.claim_token != claim_token
            or task.claim_until is None
            or task.claim_until <= checked_at
            or attempt is None
            or attempt.task_id != task_id
            or attempt.status != "running"
            or attempt.claim_token != claim_token
            or attempt.lease_until <= checked_at
        ):
            raise ConflictError(
                "runtime cost policy check lost its Task lease"
            )

        snapshot = deepcopy(provider_snapshot or {})
        normalized_phase = str(phase or "preflight")[:40]
        message = (
            "Provider model has no explicit pricing under the project's "
            "strict cost policy."
            if normalized_phase == "preflight"
            else (
                "Provider response did not include the usage required by "
                "the project's strict cost policy."
            )
        )
        violation = {
            "dimension": "unpriced_provider",
            "code": "unpriced_provider",
            "limit": 0,
            "actual": 1,
            "policy_mode": "block",
            "phase": normalized_phase,
            "message": message,
            "provider_profile_id": str(
                snapshot.get("provider_profile_id") or ""
            ),
            "provider_name": str(snapshot.get("provider_name") or ""),
            "model_profile_id": str(
                snapshot.get("model_profile_id") or ""
            ),
            "model_id": str(snapshot.get("model_id") or ""),
            "cost_entry_id": str(cost_entry_id or ""),
        }
        identity = json.dumps(
            {
                "task_id": task_id,
                "phase": normalized_phase,
                "provider_profile_id": violation["provider_profile_id"],
                "model_id": violation["model_id"],
                "cost_entry_id": violation["cost_entry_id"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()
        event = self._append_governance_event_once(
            plan_id,
            "runtime.cost_policy.blocked",
            f"runtime.cost_policy.blocked:{digest}",
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "turn_id": (
                    plan.subject_id
                    if plan.subject_type == "agent_turn"
                    else ""
                ),
                "type": "cost_policy.blocked",
                "violation": violation,
                "provider_snapshot": snapshot,
            },
            created_at=checked_at,
        )
        return {"violation": violation, "event": event}


__all__ = ["RuntimeCostPolicyRepositoryMixin"]
