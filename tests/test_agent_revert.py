import pytest

from app.application.agent.revert import revert_agent_turn
from app.store import UnitOfWork
from app.store.repositories import ConflictError, NotFoundError


def _turn_with_artifact(app, project_id: str):
    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(project_id, None, "撤销测试")
        turn = uow.agent_turns.create(
            conversation["id"],
            project_id,
            None,
            [],
        )
        artifact = uow.artifacts.create(
            project_id=project_id,
            unit_id=None,
            kind="generated",
            name="AI 草稿",
            schema_id="freeform",
            payload={"body": "draft"},
            source="ai",
        )
        uow.agent_turns.record_entity(turn["id"], "artifact", artifact["id"])
        uow.agent_turns.set_status(turn["id"], "succeeded")
        return turn["id"], artifact


def test_revert_removes_pristine_ai_artifact(app, project):
    turn_id, artifact = _turn_with_artifact(app, project["id"])

    result = revert_agent_turn(app.state.database, turn_id)

    assert result["reverted"] == [{"type": "artifact", "id": artifact["id"]}]
    assert result["turn"]["status"] == "reverted"
    with UnitOfWork(app.state.database) as uow:
        with pytest.raises(NotFoundError):
            uow.artifacts.get(artifact["id"])


def test_revert_preserves_artifact_after_user_change(app, project):
    turn_id, artifact = _turn_with_artifact(app, project["id"])
    with UnitOfWork(app.state.database) as uow:
        uow.artifacts.add_version(
            artifact["id"],
            {"body": "user revision"},
            source="user",
        )

    result = revert_agent_turn(app.state.database, turn_id)

    assert result["reverted"] == []
    assert result["skipped"] == [
        {
            "type": "artifact",
            "id": artifact["id"],
            "reason": "artifact_has_later_versions",
        }
    ]
    with UnitOfWork(app.state.database) as uow:
        assert uow.artifacts.get(artifact["id"])["current_version"]["version"] == 2


def test_revert_requires_running_turn_to_be_canceled(app, project):
    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(project["id"], None, "运行中")
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
            None,
            [],
        )

    with pytest.raises(ConflictError, match="先取消"):
        revert_agent_turn(app.state.database, turn["id"])
