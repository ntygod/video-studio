"""Idempotent command execution with durable operation audit."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from app.store import UnitOfWork
from app.store.repositories import ConflictError


class CommandValidationError(ValueError):
    """The requested semantic operation violates its input contract."""


@dataclass(frozen=True, slots=True)
class CommandContext:
    actor_type: str = "user"
    actor_id: str = "local"
    request_id: str = ""
    turn_id: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class OperationExecution:
    result: Any
    affected_entities: list[dict[str, Any]]
    inverse_operation: dict[str, Any] | None = None
    audit_result: Any = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    operation: dict[str, Any]
    result: Any
    replayed: bool = False


class SemanticCommand(Protocol):
    operation_type: str
    risk_level: str
    project_id: str | None
    target_type: str
    target_id: str
    idempotency_scope: str

    def arguments(self) -> dict[str, Any]: ...

    def preconditions(self) -> list[dict[str, Any]]: ...

    def prepare(self, uow: UnitOfWork) -> None: ...

    def execute(self, uow: UnitOfWork) -> OperationExecution: ...

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> Any: ...


class CommandBus:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _audit_arguments(
        command: SemanticCommand,
    ) -> dict[str, Any]:
        arguments = command.arguments()
        if "idempotency_scope" in arguments:
            raise RuntimeError(
                "command arguments reserve idempotency_scope"
            )
        return {
            "idempotency_scope": command.idempotency_scope,
            **arguments,
        }

    @classmethod
    def _assert_same_command(
        cls,
        existing: dict[str, Any],
        command: SemanticCommand,
    ) -> None:
        if (
            existing["operation_type"] != command.operation_type
            or existing["arguments"]
            != cls._audit_arguments(command)
        ):
            raise ConflictError(
                "Idempotency-Key 已被另一个操作使用"
            )

    def _existing_result(
        self,
        command: SemanticCommand,
        context: CommandContext,
    ) -> CommandResult | None:
        key = context.idempotency_key or ""
        if not key:
            return None
        with UnitOfWork(self.database) as uow:
            existing = uow.operations.find_by_idempotency_key(key)
        if existing is None:
            return None
        self._assert_same_command(existing, command)
        if existing["status"] == "succeeded":
            with UnitOfWork(self.database) as uow:
                result = command.replay(
                    uow,
                    existing["result"],
                )
            return CommandResult(
                operation=existing,
                result=result,
                replayed=True,
            )
        if existing["status"] == "running":
            raise ConflictError("相同操作仍在执行")
        raise ConflictError(
            "相同 Idempotency-Key 的上次操作已失败；"
            "请确认后使用新的 key 重试"
        )

    def _create_operation(
        self,
        command: SemanticCommand,
        context: CommandContext,
    ) -> dict[str, Any]:
        with UnitOfWork(self.database) as uow:
            return uow.operations.create(
                {
                    "project_id": command.project_id,
                    "operation_type": command.operation_type,
                    "actor_type": context.actor_type,
                    "actor_id": context.actor_id,
                    "request_id": context.request_id,
                    "turn_id": context.turn_id,
                    "target_type": command.target_type,
                    "target_id": command.target_id,
                    "risk_level": command.risk_level,
                    "idempotency_key": (
                        context.idempotency_key or None
                    ),
                    "arguments": self._audit_arguments(command),
                    "preconditions": command.preconditions(),
                }
            )

    def _mark_failed(
        self,
        operation_id: str,
        exc: BaseException,
    ) -> None:
        try:
            with UnitOfWork(self.database) as uow:
                uow.operations.fail(operation_id, str(exc))
        except Exception:
            # Preserve the original business error. Request logging captures
            # a secondary audit failure without hiding the root cause.
            pass

    def execute(
        self,
        command: SemanticCommand,
        context: CommandContext,
    ) -> CommandResult:
        replay = self._existing_result(command, context)
        if replay is not None:
            return replay

        # Resolve project ownership and target existence before creating the
        # audit row. A failed write intent is still persisted, possibly
        # without project scope when the target itself does not exist.
        try:
            with UnitOfWork(self.database) as uow:
                command.prepare(uow)
        except Exception as exc:
            operation = None
            try:
                operation = self._create_operation(command, context)
            except IntegrityError:
                replay = self._existing_result(command, context)
                if replay is not None:
                    return replay
            if operation is not None:
                self._mark_failed(operation["id"], exc)
            raise

        try:
            operation = self._create_operation(command, context)
        except IntegrityError as exc:
            replay = self._existing_result(command, context)
            if replay is not None:
                return replay
            raise ConflictError(
                "操作幂等键发生并发冲突"
            ) from exc

        binder = getattr(command, "bind_operation_id", None)
        if binder is not None:
            binder(operation["id"])

        try:
            # Business mutation and operation completion commit together.
            # Large payloads are not duplicated in the audit row: commands
            # persist compact references and know how to reconstruct a replay.
            with UnitOfWork(self.database) as uow:
                execution = command.execute(uow)
                audit_result = (
                    execution.audit_result
                    if execution.audit_result is not None
                    else execution.result
                )
                completed = uow.operations.succeed(
                    operation["id"],
                    result=audit_result,
                    affected_entities=execution.affected_entities,
                    inverse_operation=execution.inverse_operation,
                )
            return CommandResult(
                operation=completed,
                result=execution.result,
            )
        except Exception as exc:
            self._mark_failed(operation["id"], exc)
            raise


_bus_lock = threading.Lock()


def get_command_bus(app) -> CommandBus:
    bus = getattr(app.state, "command_bus", None)
    if bus is not None:
        return bus
    with _bus_lock:
        bus = getattr(app.state, "command_bus", None)
        if bus is None:
            bus = CommandBus(app.state.database)
            app.state.command_bus = bus
    return bus
