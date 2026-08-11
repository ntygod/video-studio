"""Repository for durable OperationLog records."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from .json_codec import dumps, loads
from .operation_models import OperationLogRow
from .repositories import NotFoundError, new_id


class OperationLogRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _data(row: OperationLogRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "operation_type": row.operation_type,
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "request_id": row.request_id,
            "turn_id": row.turn_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "risk_level": row.risk_level,
            "status": row.status,
            "idempotency_key": row.idempotency_key,
            "arguments": loads(row.arguments_json, {}),
            "preconditions": loads(row.preconditions_json, []),
            "affected_entities": loads(row.affected_entities_json, []),
            "inverse_operation": loads(row.inverse_json, None),
            "result": loads(row.result_json, None),
            "error": row.error,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        row = OperationLogRow(
            id=data.get("id") or new_id(),
            project_id=data.get("project_id"),
            operation_type=data["operation_type"],
            actor_type=data.get("actor_type") or "user",
            actor_id=data.get("actor_id") or "local",
            request_id=data.get("request_id") or "",
            turn_id=data.get("turn_id") or "",
            target_type=data.get("target_type") or "",
            target_id=data.get("target_id") or "",
            risk_level=data.get("risk_level") or "low",
            status="running",
            idempotency_key=data.get("idempotency_key") or None,
            arguments_json=dumps(data.get("arguments") or {}),
            preconditions_json=dumps(data.get("preconditions") or []),
            affected_entities_json="[]",
            inverse_json="null",
            result_json="null",
            error="",
            created_at=time.time(),
            completed_at=None,
        )
        self.session.add(row)
        self.session.flush()
        return self._data(row)

    def get(self, operation_id: str) -> dict[str, Any]:
        row = self.session.get(OperationLogRow, operation_id)
        if row is None:
            raise NotFoundError(operation_id)
        return self._data(row)

    def find_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        row = self.session.scalar(select(OperationLogRow).where(OperationLogRow.idempotency_key == idempotency_key))
        return self._data(row) if row else None

    def succeed(self, operation_id: str, *, result: Any, affected_entities: list[dict[str, Any]], inverse_operation: dict[str, Any] | None) -> dict[str, Any]:
        row = self.session.get(OperationLogRow, operation_id)
        if row is None:
            raise NotFoundError(operation_id)
        row.status = "succeeded"
        row.result_json = dumps(result)
        row.affected_entities_json = dumps(affected_entities)
        row.inverse_json = dumps(inverse_operation)
        row.error = ""
        row.completed_at = time.time()
        self.session.flush()
        return self._data(row)

    def fail(self, operation_id: str, error: str) -> dict[str, Any]:
        row = self.session.get(OperationLogRow, operation_id)
        if row is None:
            raise NotFoundError(operation_id)
        row.status = "failed"
        row.error = error
        row.completed_at = time.time()
        self.session.flush()
        return self._data(row)

    def fail_running(self, error: str = "operation interrupted before commit") -> int:
        rows = self.session.scalars(
            select(OperationLogRow).where(OperationLogRow.status == "running")
        ).all()
        if not rows:
            return 0
        completed_at = time.time()
        for row in rows:
            row.status = "failed"
            row.error = error
            row.completed_at = completed_at
        self.session.flush()
        return len(rows)

    def list(self, project_id: str | None = None, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query = select(OperationLogRow)
        if project_id:
            query = query.where(OperationLogRow.project_id == project_id)
        if status:
            query = query.where(OperationLogRow.status == status)
        rows = self.session.scalars(query.order_by(OperationLogRow.created_at.desc(), OperationLogRow.id.desc()).limit(limit)).all()
        return [self._data(row) for row in rows]
