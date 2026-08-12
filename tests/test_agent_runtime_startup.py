import threading
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
from app.application.task_runtime import TaskRuntime
from app.application.task_runtime_engine import TaskExecutionContext
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


def _wait_plan(database, plan_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with UnitOfWork(database) as uow:
            plan = uow.task_runtime.get_plan(plan_id)
        if plan["status"] in {
            "succeeded",
            "failed",
            "blocked",
            "canceled",
        }:
            return plan
        time.sleep(0.02)
    raise AssertionError(f"Runtime Plan did not finish: {plan}")


def _context(
    runtime: TaskRuntime,
    claim: dict,
    lease_seconds: float,
) -> TaskExecutionContext:
    return TaskExecutionContext.from_claim(
        runtime,
        claim,
        lease_seconds,
        threading.Event(),
    )


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
            # AgentTurn is committed inside the handler. RuntimeTask completion
            # follows immediately afterward, so observe both before lifespan
            # shutdown stops the worker pool.
            stored_plan = _wait_plan(
                app.state.database,
                plan["id"],
            )
        assert finished["status"] == "succeeded"
        assert adapter.calls == 1
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
        should_crash = False
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
                should_crash = True
        if should_crash:
            committed["done"] = True
            # The business transaction has committed. The process dies before
            # RuntimeTaskEvent and RuntimeTask completion can be appended.
            raise BaseException("simulated process death")
        return {
            "turn_id": turn["id"],
            "assistant_message_id": stored["assistant_message_id"],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    runtime = TaskRuntime(app.state.database)
    logical_now = time.time() + 1
    first_claim = runtime.claim_next(
        "agent-before-crash",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=5,
        now=logical_now,
    )
    assert first_claim is not None
    first_executor = DurableAgentTurnExecutor(
        app.state.database,
        app.state.settings,
        job_engine,
        workers=1,
        runner=terminal_commit_runner,
    )
    try:
        try:
            first_executor._handle_turn(
                _context(runtime, first_claim, 5)
            )
            raise AssertionError("simulated process death did not occur")
        except BaseException as exc:
            assert str(exc) == "simulated process death"
        assert committed["done"] is True

        # Recovery and the restarted claim use the same injected clock. This
        # models real wall time advancing beyond the old lease without asking
        # a real-time worker to claim a task scheduled 120 seconds ahead.
        assert runtime.recover(
            now=logical_now + 6,
            kinds={AGENT_PLAN_KIND},
        ) == 1
        replay_claim = runtime.claim_next(
            "agent-after-restart",
            kinds={AGENT_PLAN_KIND},
            lease_seconds=5,
            now=logical_now + 7,
        )
        assert replay_claim is not None

        restarted = DurableAgentTurnExecutor(
            app.state.database,
            app.state.settings,
            job_engine,
            workers=1,
            runner=terminal_commit_runner,
        )
        try:
            replay_context = _context(runtime, replay_claim, 5)
            result = restarted._handle_turn(replay_context)
            runtime.complete(
                replay_claim,
                result=result,
                checkpoint=replay_context.checkpoint,
                usage=replay_context.usage,
                now=logical_now + 8,
            )
            stored_plan = runtime.get_plan(plan["id"])
            assert stored_plan["status"] == "succeeded"
            event_types = [
                event["event_type"]
                for event in runtime.events(plan["id"])
            ]
            assert event_types.count("agent.message") == 1
            assert event_types.count("agent.done") == 1
        finally:
            restarted.shutdown()
    finally:
        first_executor.shutdown()
