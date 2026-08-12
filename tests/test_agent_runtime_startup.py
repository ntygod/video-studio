import time

from fastapi.testclient import TestClient

from app.application.agent.durable_executor import (
    DurableAgentTurnExecutor,
)
from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
    run_durable_agent_turn,
)
from app.integrations.llm.base import ChatChunk
from app.store import UnitOfWork


class NoopJobEngine:
    def submit(self, _job_id: str) -> None:
        return

    def cancel(self, _job_id: str) -> None:
        return


class FinalAdapter:
    supports_native_tools = True

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def stream(self, _messages, _tools, **_kwargs):
        self.calls += 1
        yield ChatChunk(kind="token", text=self.text)


def _wait_turn(client: TestClient, turn_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = client.get(f"/api/turns/{turn_id}").json()
        if turn["status"] in {"succeeded", "failed", "canceled"}:
            return turn
        time.sleep(0.02)
    raise AssertionError(f"Agent Turn did not finish: {turn}")


def test_application_startup_recovers_queued_agent_plan(
    app,
    project,
):
    adapter = FinalAdapter("启动恢复完成")
    job_engine = NoopJobEngine()

    def runner(database, settings, engine, context, **kwargs):
        return run_durable_agent_turn(
            database,
            settings,
            engine,
            context,
            adapter=adapter,
            **kwargs,
        )

    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(
            project["id"],
            None,
            "启动恢复",
        )
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "服务启动后继续执行",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user["id"],
        )
        plan = uow.task_runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="agent_turn",
            subject_id=turn["id"],
            idempotency_key=f"agent-turn:{turn['id']}",
        )
        uow.task_runtime.add_task(
            plan["id"],
            task_key="execute",
            task_type=AGENT_TASK_TYPE,
            payload={"turn_id": turn["id"]},
            max_attempts=2,
            timeout_seconds=60,
        )
        uow.task_runtime.queue_plan(plan["id"])

    previous = getattr(app.state, "agent_turn_executor", None)
    if previous is not None:
        previous.shutdown()
    executor = DurableAgentTurnExecutor(
        app.state.database,
        app.state.settings,
        job_engine,
        workers=1,
        runner=runner,
    )
    app.state.job_engine = job_engine
    app.state.agent_turn_executor = executor
    try:
        with TestClient(app) as lifecycle_client:
            finished = _wait_turn(lifecycle_client, turn["id"])
        assert finished["status"] == "succeeded"
        assert adapter.calls == 1
        with UnitOfWork(app.state.database) as uow:
            stored_plan = uow.task_runtime.get_plan(plan["id"])
        assert stored_plan["status"] == "succeeded"
        assert stored_plan["tasks"][0]["attempts"][0]["status"] == (
            "succeeded"
        )
    finally:
        executor.shutdown()


def test_executor_repairs_events_after_terminal_commit_window(
    app,
    project,
):
    job_engine = NoopJobEngine()

    with UnitOfWork(app.state.database) as uow:
        conversation = uow.conversations.create(
            project["id"],
            None,
            "终态事件恢复",
        )
        user = uow.conversations.add_message(
            conversation["id"],
            "user",
            "完成后模拟断电",
        )
        turn = uow.agent_turns.create(
            conversation["id"],
            project["id"],
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user["id"],
        )
        plan = uow.task_runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="agent_turn",
            subject_id=turn["id"],
            idempotency_key=f"agent-turn:{turn['id']}",
        )
        uow.task_runtime.add_task(
            plan["id"],
            task_key="execute",
            task_type=AGENT_TASK_TYPE,
            payload={"turn_id": turn["id"]},
            max_attempts=2,
        )
        uow.task_runtime.queue_plan(plan["id"])

    committed = {"done": False}

    def terminal_commit_runner(database, _settings, _engine, context, **_kwargs):
        with UnitOfWork(database) as uow:
            stored = uow.agent_turns.get(turn["id"])
            if stored["status"] != "succeeded":
                message = uow.conversations.add_message(
                    conversation["id"],
                    "assistant",
                    "事实已提交，事件尚未提交",
                )
                uow.agent_turns.set_messages(
                    turn["id"],
                    assistant_message_id=message["id"],
                )
                uow.agent_turns.set_status(turn["id"], "succeeded")
                committed["done"] = True
                raise BaseException("simulated process death")
        return {
            "turn_id": turn["id"],
            "assistant_message_id": stored["assistant_message_id"],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    executor = DurableAgentTurnExecutor(
        app.state.database,
        app.state.settings,
        job_engine,
        workers=1,
        runner=terminal_commit_runner,
    )
    try:
        executor.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not committed["done"]:
            time.sleep(0.02)
        assert committed["done"] is True
        executor.shutdown()

        # The daemon-style crash leaves the first lease running. Recover it
        # immediately and use a fresh executor as the restarted process.
        with UnitOfWork(app.state.database) as uow:
            assert uow.task_runtime.recover_expired(
                now=time.time() + 120,
                kinds={AGENT_PLAN_KIND},
            ) == 1

        restarted = DurableAgentTurnExecutor(
            app.state.database,
            app.state.settings,
            job_engine,
            workers=1,
            runner=terminal_commit_runner,
        )
        restarted.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with UnitOfWork(app.state.database) as uow:
                    stored_plan = uow.task_runtime.get_plan(plan["id"])
                if stored_plan["status"] == "succeeded":
                    break
                time.sleep(0.02)
            assert stored_plan["status"] == "succeeded"
            event_types = [
                event["event_type"]
                for event in restarted._engine.runtime.events(plan["id"])
            ]
            assert event_types.count("agent.message") == 1
            assert event_types.count("agent.done") == 1
        finally:
            restarted.shutdown()
    finally:
        executor.shutdown()
