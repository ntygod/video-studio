"""Stable Agent tool-step identities for crash-safe CommandBus replay."""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from typing import Any

from sqlalchemy import func, select

from app.store.json_codec import dumps, loads
from app.store.models import AgentStepRow, AgentTurnRow
from app.store.repositories import ConflictError, NotFoundError

LOGICAL_CALL_ARGUMENT = "_logical_call_id"
REQUEST_ID_ARGUMENT = "_request_id"


def stable_tool_step_id(turn_id: str, logical_call_id: str) -> str:
    normalized_turn = str(turn_id or "").strip()
    normalized_call = str(logical_call_id or "").strip()
    if not normalized_turn or not normalized_call:
        raise ValueError("turn_id and logical_call_id are required")
    encoded = (
        "agent-tool-step\0" + normalized_turn + "\0" + normalized_call
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _step_data(row: AgentStepRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "turn_id": row.turn_id,
        "seq": row.seq,
        "kind": row.kind,
        "tool_name": row.tool_name,
        "arguments": loads(row.arguments_json, {}),
        "result": loads(row.result_json, {}),
        "summary": row.summary,
        "status": row.status,
        "error": row.error,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
    }


def _identity_arguments(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result.pop(REQUEST_ID_ARGUMENT, None)
    return result


def ensure_tool_step(
    uow,
    *,
    turn_id: str,
    logical_call_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create or replay one logical tool call with a deterministic Step ID.

    The Step is committed before a mutating tool enters CommandBus. If the
    process dies after the command commits but before the Step is finished, a
    later RuntimeTask Attempt reconstructs the same Step ID and therefore the
    same ``agent:{turn_id}:{step_id}`` idempotency key.
    """

    turn = uow.session.get(AgentTurnRow, turn_id)
    if turn is None:
        raise NotFoundError(turn_id)
    normalized_call = str(logical_call_id or "").strip()
    normalized_tool = str(tool_name or "").strip()
    if not normalized_call or not normalized_tool:
        raise ValueError("logical_call_id and tool_name are required")

    normalized_arguments = deepcopy(arguments or {})
    normalized_arguments[LOGICAL_CALL_ARGUMENT] = normalized_call
    if request_id:
        normalized_arguments[REQUEST_ID_ARGUMENT] = request_id

    step_id = stable_tool_step_id(turn_id, normalized_call)
    existing = uow.session.get(AgentStepRow, step_id)
    if existing is not None:
        if (
            existing.turn_id != turn_id
            or existing.kind != "tool"
            or existing.tool_name != normalized_tool
            or _identity_arguments(
                loads(existing.arguments_json, {})
            )
            != _identity_arguments(normalized_arguments)
        ):
            raise ConflictError(
                "logical Agent tool call changed during recovery"
            )
        return _step_data(existing)

    sequence = int(
        uow.session.scalar(
            select(func.coalesce(func.max(AgentStepRow.seq), 0)).where(
                AgentStepRow.turn_id == turn_id
            )
        )
        or 0
    ) + 1
    row = AgentStepRow(
        id=step_id,
        turn_id=turn_id,
        seq=sequence,
        kind="tool",
        tool_name=normalized_tool,
        arguments_json=dumps(normalized_arguments),
        result_json="{}",
        summary="",
        status="running",
        error="",
        duration_ms=0,
        created_at=time.time(),
    )
    uow.session.add(row)
    uow.session.flush()
    return _step_data(row)


__all__ = [
    "LOGICAL_CALL_ARGUMENT",
    "ensure_tool_step",
    "stable_tool_step_id",
]
