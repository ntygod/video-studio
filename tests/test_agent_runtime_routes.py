import json
import threading
import time

from app.application.agent.durable_executor import (
    DurableAgentTurnExecutor,
)
from app.application.agent.durable_loop import run_durable_agent_turn
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
        yield ChatChunk(
            kind="usage",
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        )


def _wait_turn(client, turn_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = client.get(f"/api/turns/{turn_id}").json()
        if turn["status"] in {"succeeded", "failed", "canceled"}:
            return turn
        time.sleep(0.02)
    raise AssertionError(f"Agent Turn did not finish: {turn}")


def _events(response_text: str):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def test_turn_route_commits_runtime_plan_and_replays_durable_sse(
    app,
    client,
    project,
):
    adapter = FinalAdapter("耐久回复")

    def runner(database, settings, job_engine, context, **kwargs):
        return run_durable_agent_turn(
            database,
            settings,
            job_engine,
            context,
            adapter=adapter,
            **kwargs,
        )

    app.state.job_engine = NoopJobEngine()
    executor = DurableAgentTurnExecutor(
        app.state.database,
        app.state.settings,
        app.state.job_engine,
        workers=1,
        runner=runner,
    )
    app.state.agent_turn_executor = executor
    try:
        conversation = client.post(
            f"/api/projects/{project['id']}/conversations",
            json={"title": "运行时路由"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/turns",
            json={"content": "给我回复", "context_refs": []},
        )
        assert started.status_code == 201, started.text
        body = started.json()

        with UnitOfWork(app.state.database) as uow:
            plan = uow.task_runtime.get_plan(body["runtime_plan_id"])
            by_subject = uow.task_runtime.find_plan_by_subject(
                "agent_turn",
                body["turn_id"],
                kind="agent.turn",
            )
        assert by_subject is not None
        assert by_subject["id"] == plan["id"]
        assert plan["subject_id"] == body["turn_id"]
        assert plan["tasks"][0]["task_type"] == "agent.turn.execute"

        turn = _wait_turn(client, body["turn_id"])
        assert turn["status"] == "succeeded"
        assert turn["runtime_plan_id"] == plan["id"]
        assert adapter.calls == 1

        streamed = client.get(
            f"/api/conversations/{conversation['id']}/stream",
            params={"turn_id": body["turn_id"]},
        )
        assert streamed.status_code == 200, streamed.text
        events = _events(streamed.text)
        message = next(
            event for event in events if event["type"] == "message"
        )
        done = next(event for event in events if event["type"] == "done")
        assert message["text"] == "耐久回复"
        assert done["failed"] is False
        assert done["canceled"] is False
        durable_ids = [
            event["id"]
            for event in events
            if str(event.get("id") or "").startswith(
                body["turn_id"] + ":"
            )
        ]
        assert durable_ids
    finally:
        executor.shutdown()


def test_cancel_turn_cancels_runtime_plan_and_attempt(
    app,
    client,
    project,
):
    entered = threading.Event()

    def blocking_runner(
        _database,
        _settings,
        _job_engine,
        context,
        **_kwargs,
    ):
        entered.set()
        while True:
            context.raise_if_cancelled()
            time.sleep(0.01)

    app.state.job_engine = NoopJobEngine()
    executor = DurableAgentTurnExecutor(
        app.state.database,
        app.state.settings,
        app.state.job_engine,
        workers=1,
        runner=blocking_runner,
    )
    app.state.agent_turn_executor = executor
    try:
        conversation = client.post(
            f"/api/projects/{project['id']}/conversations",
            json={"title": "取消运行时"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/turns",
            json={"content": "保持运行", "context_refs": []},
        ).json()
        assert entered.wait(timeout=3)

        canceled = client.post(
            f"/api/turns/{started['turn_id']}/cancel"
        )
        assert canceled.status_code == 200, canceled.text
        turn = _wait_turn(client, started["turn_id"])
        assert turn["status"] == "canceled"

        with UnitOfWork(app.state.database) as uow:
            plan = uow.task_runtime.get_plan(
                started["runtime_plan_id"]
            )
        assert plan["status"] == "canceled"
        assert plan["tasks"][0]["status"] == "canceled"
        assert plan["tasks"][0]["attempts"][0]["status"] == (
            "canceled"
        )

        streamed = client.get(
            f"/api/conversations/{conversation['id']}/stream",
            params={"turn_id": started["turn_id"]},
        )
        events = _events(streamed.text)
        done = next(event for event in events if event["type"] == "done")
        assert done["canceled"] is True
        assert done["failed"] is False
    finally:
        executor.shutdown()
