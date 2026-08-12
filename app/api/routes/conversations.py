import json
import queue
import re
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.logging import request_id_var
from app.application.agent.durable_executor import (
    get_durable_agent_turn_executor,
)
from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.agent.revert import revert_agent_turn
from app.application.job_engine import get_job_engine
from app.store import UnitOfWork
from app.store.repositories import NotFoundError

router = APIRouter(tags=["conversations"])

_turn_queues: dict[str, set[queue.Queue]] = {}
_lock = threading.Lock()


def _sse(event: dict[str, Any]) -> str:
    event_id = str(event.get("id") or "")
    data = dict(event)
    rid = request_id_var.get()
    if rid:
        data.setdefault("request_id", rid)
    payload = json.dumps(data, ensure_ascii=False)
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {payload}\n\n"


def _publish(turn_id: str, event: dict[str, Any]) -> None:
    with _lock:
        queues = list(_turn_queues.get(turn_id, ()))
    for item in queues:
        item.put(dict(event))


def _runtime_plan(uow: UnitOfWork, turn_id: str):
    return uow.task_runtime.find_plan_by_subject(
        "agent_turn",
        turn_id,
        kind=AGENT_PLAN_KIND,
    )


def _runtime_event(turn_id: str, event: dict[str, Any]):
    payload = dict(event.get("payload") or {})
    event_type = str(payload.get("type") or "")
    if not event_type:
        stored_type = str(event.get("event_type") or "")
        event_type = (
            stored_type.removeprefix("agent.")
            if stored_type.startswith("agent.")
            else stored_type
        )
        payload["type"] = event_type
    payload["id"] = f"{turn_id}:{event['seq']}"
    payload["seq"] = event["seq"]
    return payload


def _event_seq(turn_id: str, event_id: str | None) -> int | None:
    if not event_id:
        return None
    match = re.fullmatch(
        re.escape(turn_id) + r":(\d+)",
        str(event_id),
    )
    return int(match.group(1)) if match else None


def _terminal_message(uow: UnitOfWork, turn: dict[str, Any]) -> str:
    message_id = turn.get("assistant_message_id")
    if not message_id:
        return ""
    for message in uow.conversations.list_messages(
        turn["conversation_id"]
    ):
        if message["id"] == message_id:
            return str(message.get("content") or "")
    return ""


class ConversationCreate(BaseModel):
    title: str = "新对话"
    unit_id: str | None = None


class TurnCreate(BaseModel):
    content: str
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = "default"


@router.get("/api/projects/{project_id}/conversations")
def list_conversations(
    project_id: str,
    request: Request,
    unit_id: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.conversations.list(project_id, unit_id=unit_id)


@router.post(
    "/api/projects/{project_id}/conversations",
    status_code=201,
)
def post_conversation(
    project_id: str,
    data: ConversationCreate,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        if data.unit_id:
            unit = uow.units.get(data.unit_id)
            if unit.project_id != project_id:
                raise NotFoundError(data.unit_id)
        return uow.conversations.create(
            project_id,
            data.unit_id,
            data.title,
        )


@router.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.conversations.get(conversation_id)


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.conversations.delete(conversation_id)
    return {"ok": True}


@router.post(
    "/api/conversations/{conversation_id}/turns",
    status_code=201,
)
def post_turn(
    conversation_id: str,
    data: TurnCreate,
    request: Request,
):
    content = data.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    database = request.app.state.database
    request_id = str(getattr(request.state, "request_id", "") or "")
    with UnitOfWork(database) as uow:
        conversation = uow.conversations.get(conversation_id)
        user_message = uow.conversations.add_message(
            conversation_id,
            "user",
            content,
        )
        turn = uow.agent_turns.create(
            conversation_id,
            conversation["project_id"],
            conversation.get("unit_id"),
            data.context_refs,
        )
        uow.agent_turns.set_messages(
            turn["id"],
            user_message_id=user_message["id"],
        )
        plan = uow.task_runtime.create_plan(
            project_id=conversation["project_id"],
            kind=AGENT_PLAN_KIND,
            subject_type="agent_turn",
            subject_id=turn["id"],
            idempotency_key=f"agent-turn:{turn['id']}",
            input={
                "conversation_id": conversation_id,
                "mode": data.mode,
                "request_id": request_id,
            },
        )
        uow.task_runtime.add_task(
            plan["id"],
            task_key="execute",
            task_type=AGENT_TASK_TYPE,
            payload={
                "turn_id": turn["id"],
                "request_id": request_id,
                "mode": data.mode,
            },
            policy={"retry_unhandled": False},
            max_attempts=3,
            timeout_seconds=900,
        )
        plan = uow.task_runtime.queue_plan(plan["id"])

    try:
        job_engine = get_job_engine(request.app)
        executor = get_durable_agent_turn_executor(
            request.app,
            job_engine,
        )
        executor.submit(
            turn["id"],
            lambda event: _publish(turn["id"], event),
            request_id=request_id,
        )
    except Exception:
        # The Turn and RuntimePlan are already committed. A later stream,
        # poll, or process restart can wake the durable worker safely.
        pass

    from app.application.agent.compaction import (
        maybe_compact_conversation,
    )

    maybe_compact_conversation(
        database,
        get_job_engine(request.app),
        conversation_id,
    )
    return {
        "turn_id": turn["id"],
        "runtime_plan_id": plan["id"],
        "user_message": user_message,
    }


@router.get("/api/conversations/{conversation_id}/stream")
def stream_turn(
    conversation_id: str,
    request: Request,
    turn_id: str,
    last_event_id: str | None = None,
):
    database = request.app.state.database
    with UnitOfWork(database) as uow:
        turn = uow.agent_turns.get(turn_id)
        if turn["conversation_id"] != conversation_id:
            raise NotFoundError(turn_id)

    turn_queue: queue.Queue = queue.Queue()
    with _lock:
        _turn_queues.setdefault(turn_id, set()).add(turn_queue)

    if turn["status"] == "running":
        try:
            executor = get_durable_agent_turn_executor(
                request.app,
                get_job_engine(request.app),
            )
            executor.submit(
                turn_id,
                lambda event: _publish(turn_id, event),
                request_id=str(
                    getattr(request.state, "request_id", "") or ""
                ),
            )
        except Exception:
            pass

    def event_source():
        try:
            last_seq = _event_seq(turn_id, last_event_id) or 0
            with UnitOfWork(database) as uow:
                stored_turn = uow.agent_turns.get(turn_id)
                plan = _runtime_plan(uow, turn_id)
                durable_events = (
                    uow.task_runtime.list_events(
                        plan["id"],
                        after_seq=last_seq,
                        limit=1000,
                    )
                    if plan is not None
                    else []
                )
                terminal_text = _terminal_message(uow, stored_turn)

            replayed_done = False
            replayed_message = False
            if plan is not None:
                for stored_event in durable_events:
                    event = _runtime_event(turn_id, stored_event)
                    last_seq = max(last_seq, int(event["seq"]))
                    replayed_done = replayed_done or (
                        event.get("type") == "done"
                    )
                    replayed_message = replayed_message or (
                        event.get("type") == "message"
                    )
                    yield _sse(event)
                if replayed_done:
                    return
            else:
                for step in stored_turn.get("steps") or []:
                    if step["seq"] <= last_seq:
                        continue
                    if step["kind"] == "tool":
                        yield _sse(
                            {
                                "id": f"{turn_id}:{step['seq']}",
                                "type": "step.start",
                                "step_id": step["id"],
                                "tool": step["tool_name"],
                                "args_preview": json.dumps(
                                    step.get("arguments") or {},
                                    ensure_ascii=False,
                                )[:80],
                            }
                        )
                        yield _sse(
                            {
                                "id": f"{turn_id}:{step['seq']}",
                                "type": "step.done",
                                "step_id": step["id"],
                                "ok": step["status"] == "ok",
                                "duration_ms": step["duration_ms"],
                                "summary": step["summary"],
                            }
                        )
                    elif step["kind"] == "error":
                        yield _sse(
                            {
                                "id": f"{turn_id}:{step['seq']}",
                                "type": "error",
                                "message": step["error"],
                                "recoverable": False,
                            }
                        )

            status = stored_turn.get("status")
            if status in ("succeeded", "failed", "canceled"):
                if terminal_text and not replayed_message:
                    yield _sse(
                        {
                            "type": "message",
                            "message_id": stored_turn.get(
                                "assistant_message_id"
                            ),
                            "text": terminal_text,
                        }
                    )
                yield _sse(
                    {
                        "type": "done",
                        "failed": status == "failed",
                        "canceled": status == "canceled",
                    }
                )
                return

            while True:
                try:
                    event = turn_queue.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                durable_seq = _event_seq(
                    turn_id,
                    str(event.get("id") or ""),
                )
                if durable_seq is not None:
                    if durable_seq <= last_seq:
                        continue
                    last_seq = durable_seq
                yield _sse(event)
                if event.get("type") == "done":
                    break
        finally:
            with _lock:
                queues = _turn_queues.get(turn_id)
                if queues is not None:
                    queues.discard(turn_queue)
                    if not queues:
                        _turn_queues.pop(turn_id, None)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/turns/{turn_id}/cancel")
def cancel_turn(turn_id: str, request: Request):
    done_event = None
    with UnitOfWork(request.app.state.database) as uow:
        turn = uow.agent_turns.get(turn_id)
        if turn["status"] == "running":
            plan = _runtime_plan(uow, turn_id)
            if plan is not None and plan["status"] in {
                "draft",
                "queued",
                "running",
                "blocked",
            }:
                stored_event = uow.task_runtime.append_event(
                    plan["id"],
                    "agent.done",
                    payload={
                        "turn_id": turn_id,
                        "type": "done",
                        "message_id": turn.get("assistant_message_id"),
                        "usage": {
                            "prompt": int(
                                turn.get("prompt_tokens") or 0
                            ),
                            "completion": int(
                                turn.get("completion_tokens") or 0
                            ),
                        },
                        "canceled": True,
                        "failed": False,
                    },
                )
                done_event = _runtime_event(turn_id, stored_event)
                uow.task_runtime.cancel_plan(
                    plan["id"],
                    reason="Agent turn canceled by user",
                )
            uow.agent_turns.set_status(turn_id, "canceled")
    if done_event is not None:
        _publish(turn_id, done_event)
    else:
        _publish(
            turn_id,
            {
                "type": "done",
                "canceled": True,
                "failed": False,
            },
        )
    return {"ok": True}


@router.post("/api/turns/{turn_id}/revert")
def revert_turn(turn_id: str, request: Request):
    return revert_agent_turn(request.app.state.database, turn_id)


@router.get("/api/turns/{turn_id}")
def get_turn(turn_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        turn = uow.agent_turns.get(turn_id)
        plan = _runtime_plan(uow, turn_id)
    if turn["status"] == "running":
        try:
            executor = get_durable_agent_turn_executor(
                request.app,
                get_job_engine(request.app),
            )
            executor.submit(
                turn_id,
                lambda event: _publish(turn_id, event),
                request_id=str(
                    getattr(request.state, "request_id", "") or ""
                ),
            )
        except Exception:
            pass
    if plan is None:
        return turn
    return {
        **turn,
        "runtime_plan_id": plan["id"],
        "runtime_status": plan["status"],
    }
