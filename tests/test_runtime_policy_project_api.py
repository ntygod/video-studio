from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.runtime_governance import GovernedTaskRuntime
from app.application.task_runtime import TaskRuntime
from app.store import UnitOfWork


def test_project_policy_decisions_are_listed_without_plan_n_plus_one(
    app,
    client,
    project,
):
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "项目审批中心"},
    ).json()
    with UnitOfWork(app.state.database) as uow:
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "生成一张概念图",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user["id"],
        )

    runtime = GovernedTaskRuntime(app.state.database)
    plan = TaskRuntime(app.state.database).create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="agent_turn",
        subject_id=turn["id"],
        idempotency_key=f"project-policy:{turn['id']}",
        input={"conversation_id": conversation["id"]},
        tasks=[
            {
                "key": "execute",
                "type": AGENT_TASK_TYPE,
                "payload": {"turn_id": turn["id"]},
            }
        ],
    )
    claim = runtime.claim_next(
        "project-policy-worker",
        kinds={AGENT_PLAN_KIND},
    )
    assert claim is not None
    with UnitOfWork(app.state.database) as uow:
        authorization = uow.task_runtime.authorize_action(
            plan_id=plan["id"],
            task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"],
            claim_token=claim["claim_token"],
            action_key="project-policy-action",
            action_type="generate_media",
            risk_level="high",
            context={
                "turn_id": turn["id"],
                "arguments": {"kind": "image"},
            },
            checkpoint={"phase": "tools"},
            usage={"prompt_tokens": 5, "completion_tokens": 2},
        )
    decision = authorization["decision"]
    assert decision["status"] == "pending"

    response = client.get(
        f"/api/projects/{project['id']}/runtime-policy-decisions",
        params={"status": "pending", "kind": AGENT_PLAN_KIND},
    )
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["id"] for item in items] == [decision["id"]]
    assert items[0]["plan"]["subject_id"] == turn["id"]
    assert items[0]["plan"]["input"]["conversation_id"] == (
        conversation["id"]
    )

    fetched = client.get(
        f"/api/runtime-policy-decisions/{decision['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["action_type"] == "generate_media"

    runtime.cancel(plan["id"], reason="test cleanup")
