"""Recover OperationLog rows left running by a previous process."""

from app.store import UnitOfWork

INTERRUPTED_OPERATION_ERROR = "operation interrupted before database commit"


def recover_interrupted_operations(database, media_store=None) -> int:
    with UnitOfWork(database) as uow:
        operations = uow.operations.list(status="running", limit=500)
    recovered = 0
    for operation in operations:
        error = INTERRUPTED_OPERATION_ERROR
        if media_store is not None:
            try:
                if operation["operation_type"] in {
                    "asset.upload", "asset.generated.persist",
                    "asset.generated-file.persist",
                }:
                    media_store.cleanup_operation_files(operation["id"])
                elif operation["operation_type"] in {
                    "asset.delete", "project.delete", "unit.delete",
                }:
                    media_store.restore_operation_quarantine(operation["id"])
            except Exception as exc:
                error += f"; external compensation failed: {exc}"
        with UnitOfWork(database) as uow:
            current = uow.operations.get(operation["id"])
            if current["status"] != "running":
                continue
            uow.operations.fail(operation["id"], error)
            recovered += 1
    return recovered
