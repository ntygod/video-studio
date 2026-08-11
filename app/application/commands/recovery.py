"""Recover OperationLog rows left running by a previous process."""

from app.store import UnitOfWork

INTERRUPTED_OPERATION_ERROR = (
    "operation interrupted before database commit"
)


def recover_interrupted_operations(
    database,
    media_store=None,
) -> int:
    """Compensate external staging, then fail inherited running operations.

    CommandBus commits the business mutation and the succeeded audit state in
    the same database transaction. A still-running upload has no committed
    Asset row, but its deterministic file may already exist and must be
    removed before the operation is marked failed.
    """

    with UnitOfWork(database) as uow:
        operations = uow.operations.list(
            status="running",
            limit=500,
        )

    recovered = 0
    for operation in operations:
        error = INTERRUPTED_OPERATION_ERROR
        if (
            media_store is not None
            and operation["operation_type"] == "asset.upload"
        ):
            try:
                media_store.cleanup_operation_files(operation["id"])
            except Exception as exc:
                error += f"; upload cleanup failed: {exc}"
        with UnitOfWork(database) as uow:
            current = uow.operations.get(operation["id"])
            if current["status"] != "running":
                continue
            uow.operations.fail(operation["id"], error)
            recovered += 1
    return recovered
