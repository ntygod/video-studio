"""Recover OperationLog rows left running by a previous process."""

from app.store import UnitOfWork

INTERRUPTED_OPERATION_ERROR = (
    "operation interrupted before database commit"
)


def recover_interrupted_operations(database) -> int:
    """Mark all inherited running operations failed.

    CommandBus commits the business mutation and the succeeded audit state in
    the same database transaction. Therefore a row that is still ``running``
    after process restart has no committed business mutation to resume.
    """

    with UnitOfWork(database) as uow:
        return uow.operations.fail_running(
            INTERRUPTED_OPERATION_ERROR
        )
