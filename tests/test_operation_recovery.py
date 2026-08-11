from app.application.commands.recovery import (
    INTERRUPTED_OPERATION_ERROR,
    recover_interrupted_operations,
)
from app.store import UnitOfWork


def test_interrupted_running_operations_fail_on_recovery(
    app,
    project,
):
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "test.interrupted",
                "target_type": "project",
                "target_id": project["id"],
                "arguments": {},
                "preconditions": [],
                "idempotency_key": "interrupted-once",
            }
        )
        operation_id = operation["id"]

    assert recover_interrupted_operations(
        app.state.database
    ) == 1
    assert recover_interrupted_operations(
        app.state.database
    ) == 0

    with UnitOfWork(app.state.database) as uow:
        recovered = uow.operations.get(operation_id)
    assert recovered["status"] == "failed"
    assert recovered["error"] == INTERRUPTED_OPERATION_ERROR
    assert recovered["completed_at"] is not None
