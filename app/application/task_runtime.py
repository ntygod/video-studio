"""Application facade for the generic durable task runtime."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Sequence

from sqlalchemy.exc import IntegrityError

from app.store import UnitOfWork


def _normalized_task_definitions(
    tasks: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, definition in enumerate(tasks):
        key = str(definition.get("key") or "").strip()
        task_type = str(
            definition.get("type")
            or definition.get("task_type")
            or ""
        ).strip()
        if not key or not task_type:
            raise ValueError(
                "runtime task definitions require key and type"
            )
        if key in keys:
            raise ValueError(f"duplicate runtime task key: {key}")
        keys.add(key)
        normalized.append(
            {
                "key": key,
                "type": task_type,
                "payload": deepcopy(definition.get("payload") or {}),
                "policy": deepcopy(definition.get("policy") or {}),
                "depends_on": list(
                    dict.fromkeys(
                        str(item)
                        for item in (
                            definition.get("depends_on") or []
                        )
                    )
                ),
                "priority": int(definition.get("priority") or 0),
                "order_index": int(
                    definition.get("order_index", index)
                ),
                "max_attempts": int(
                    definition.get("max_attempts") or 1
                ),
                "timeout_seconds": float(
                    definition.get("timeout_seconds") or 0.0
                ),
                "available_at": definition.get("available_at"),
            }
        )

    for definition in normalized:
        missing = [
            key
            for key in definition["depends_on"]
            if key not in keys
        ]
        if missing:
            raise ValueError(
                "runtime task dependency is not defined: "
                + ", ".join(missing)
            )
        if definition["key"] in definition["depends_on"]:
            raise ValueError(
                "runtime task cannot depend on itself: "
                + definition["key"]
            )

    remaining = {
        definition["key"]: set(definition["depends_on"])
        for definition in normalized
    }
    resolved: set[str] = set()
    while remaining:
        ready = sorted(
            key
            for key, dependencies in remaining.items()
            if dependencies <= resolved
        )
        if not ready:
            raise ValueError("runtime task graph contains a cycle")
        for key in ready:
            remaining.pop(key)
            resolved.add(key)
    return normalized


class TaskRuntime:
    """Small transaction boundary around ``TaskRuntimeRepository``."""

    def __init__(self, database):
        self.database = database

    def create_plan(
        self,
        *,
        project_id: str,
        kind: str,
        tasks: Sequence[dict[str, Any]],
        subject_type: str = "",
        subject_id: str = "",
        idempotency_key: str | None = None,
        priority: int = 0,
        input: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        queue: bool = True,
    ) -> dict[str, Any]:
        definitions = _normalized_task_definitions(tasks)
        if not definitions:
            raise ValueError("runtime plan requires at least one task")

        try:
            with UnitOfWork(self.database) as uow:
                uow.projects.get(project_id)
                if idempotency_key:
                    existing = (
                        uow.task_runtime.find_plan_by_idempotency(
                            kind,
                            idempotency_key,
                        )
                    )
                    if existing is not None:
                        return existing
                plan = uow.task_runtime.create_plan(
                    project_id=project_id,
                    kind=kind,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    idempotency_key=idempotency_key,
                    priority=priority,
                    input=input,
                    policy=policy,
                    budget=budget,
                )
                by_key: dict[str, str] = {}
                for definition in definitions:
                    task = uow.task_runtime.add_task(
                        plan["id"],
                        task_key=definition["key"],
                        task_type=definition["type"],
                        payload=definition["payload"],
                        policy=definition["policy"],
                        priority=definition["priority"],
                        order_index=definition["order_index"],
                        max_attempts=definition["max_attempts"],
                        timeout_seconds=definition["timeout_seconds"],
                        available_at=definition["available_at"],
                    )
                    by_key[definition["key"]] = task["id"]
                for definition in definitions:
                    uow.task_runtime.set_task_dependencies(
                        by_key[definition["key"]],
                        [
                            by_key[key]
                            for key in definition["depends_on"]
                        ],
                    )
                if queue:
                    result = uow.task_runtime.queue_plan(plan["id"])
                else:
                    result = uow.task_runtime.get_plan(plan["id"])
            return result
        except IntegrityError:
            # Two application processes may race after both observe no Plan.
            # The database unique constraint chooses the winner; the loser
            # must replay the committed Plan rather than surface a 500.
            if not idempotency_key:
                raise
            with UnitOfWork(self.database) as uow:
                existing = uow.task_runtime.find_plan_by_idempotency(
                    kind,
                    idempotency_key,
                )
            if existing is None:
                raise
            return existing

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.get_plan(plan_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.get_task(task_id)

    def claim_next(
        self,
        worker_id: str,
        *,
        kinds: Iterable[str] | None = None,
        lease_seconds: float = 60.0,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.claim_next(
                worker_id=worker_id,
                kinds=kinds,
                lease_seconds=lease_seconds,
                now=now,
            )

    def heartbeat(
        self,
        claim: dict[str, Any],
        *,
        lease_seconds: float = 60.0,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.heartbeat(
                claim["task"]["id"],
                claim["attempt"]["id"],
                claim["claim_token"],
                lease_seconds=lease_seconds,
                checkpoint=checkpoint,
                usage=usage,
                now=now,
            )

    def complete(
        self,
        claim: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.complete_task(
                claim["task"]["id"],
                claim["attempt"]["id"],
                claim["claim_token"],
                result=result,
                usage=usage,
                checkpoint=checkpoint,
                now=now,
            )

    def fail(
        self,
        claim: dict[str, Any],
        *,
        error: str,
        retryable: bool = True,
        backoff_seconds: float = 0.0,
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.fail_task(
                claim["task"]["id"],
                claim["attempt"]["id"],
                claim["claim_token"],
                error=error,
                retryable=retryable,
                backoff_seconds=backoff_seconds,
                checkpoint=checkpoint,
                usage=usage,
                now=now,
            )

    def cancel(
        self,
        plan_id: str,
        *,
        reason: str = "runtime plan canceled",
        now: float | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.cancel_plan(
                plan_id,
                reason=reason,
                now=now,
            )

    def recover(
        self,
        *,
        kinds: Iterable[str] | None = None,
        now: float | None = None,
    ) -> int:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.recover_expired(
                kinds=kinds,
                now=now,
            )

    def append_event(
        self,
        plan_id: str,
        event_type: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        payload: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.append_event(
                plan_id,
                event_type,
                task_id=task_id,
                attempt_id=attempt_id,
                payload=payload,
                created_at=now,
            )

    def events(
        self,
        plan_id: str,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with UnitOfWork(self.database) as uow:
            return uow.task_runtime.list_events(
                plan_id,
                after_seq=after_seq,
                limit=limit,
            )


__all__ = ["TaskRuntime"]
