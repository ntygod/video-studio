"""Policy and budget guard around every Agent tool handler."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable

from app.application.runtime_governance import (
    PolicyApprovalRequired,
    RuntimeBudgetExceeded,
    current_runtime_execution,
)
from app.store import UnitOfWork

from .tools import TOOL_BY_NAME, ToolContext

TOOL_RISK_LEVELS: dict[str, str] = {
    "list_units": "read",
    "read_unit": "read",
    "read_artifact": "read",
    "search": "read",
    "read_bible": "read",
    "list_assets": "read",
    "write_artifact": "medium",
    "create_units": "medium",
    "generate_media": "high",
    "propose_change": "low",
    "propose_restructure": "low",
}


def _publish(binding, event: dict[str, Any] | None) -> None:
    if (
        event is None
        or event.get("deduplicated", False)
        or binding.live_emit is None
    ):
        return
    payload = dict(event.get("payload") or {})
    payload["id"] = f"{binding.turn_id}:{event['seq']}"
    payload["seq"] = event["seq"]
    try:
        binding.live_emit(payload)
    except Exception:
        return


def _guarded_handler(
    tool_name: str,
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]],
):
    def guarded(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        binding = current_runtime_execution()
        if binding is None:
            return handler(ctx, args)
        execution = binding.context
        step_id = str(getattr(ctx, "step_id", "") or "")
        if not step_id:
            raise RuntimeError("governed Agent tool has no stable Step ID")
        risk_level = TOOL_RISK_LEVELS.get(tool_name, "high")
        serialized_args = json.dumps(
            args,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        audit_context = {
            "turn_id": binding.turn_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "arguments_sha256": hashlib.sha256(
                serialized_args.encode("utf-8")
            ).hexdigest(),
            "arguments_preview": serialized_args[:2000],
            # Only confirmation-gated actions retain full arguments in the
            # control plane. Large write payloads stay in their domain tables.
            "arguments": deepcopy(args) if risk_level == "high" else {},
        }
        with UnitOfWork(execution.runtime.database) as uow:
            authorization = uow.task_runtime.authorize_action(
                plan_id=execution.plan["id"],
                task_id=execution.task["id"],
                attempt_id=execution.attempt["id"],
                claim_token=execution.claim["claim_token"],
                action_key=step_id,
                action_type=tool_name,
                risk_level=risk_level,
                context=audit_context,
                checkpoint=execution.checkpoint,
                usage=execution.usage,
            )

        decision = dict(authorization["decision"])
        _publish(binding, authorization.get("event"))
        budget_state = authorization.get("budget_state") or {}
        violation = budget_state.get("violation")
        if violation:
            raise RuntimeBudgetExceeded(violation)
        if decision["status"] == "pending":
            raise PolicyApprovalRequired(decision)
        if decision["status"] in {"denied", "expired"}:
            raise ValueError(decision.get("reason") or "该工具动作未获批准")
        execution.raise_if_cancelled()
        usage = budget_state.get("usage") or {}
        if usage:
            execution.usage["tool_calls"] = int(
                usage.get("tool_calls") or 0
            )
        return handler(ctx, args)

    setattr(guarded, "_runtime_governed", True)
    setattr(guarded, "_runtime_original", handler)
    return guarded


def install_governed_tool_handlers() -> None:
    for name, tool in TOOL_BY_NAME.items():
        if getattr(tool.handler, "_runtime_governed", False):
            continue
        tool.handler = _guarded_handler(name, tool.handler)


__all__ = ["TOOL_RISK_LEVELS", "install_governed_tool_handlers"]
