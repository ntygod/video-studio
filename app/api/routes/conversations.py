import json
import queue
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.logging import request_id_var
from app.application.agent.loop import run_turn
from app.application.agent.revert import revert_agent_turn
from app.application.job_engine import get_job_engine
from app.store import UnitOfWork

router = APIRouter(tags=["conversations"])

_turn_queues: dict[str, set[queue.Queue]] = {}
_lock = threading.Lock()


def _sse(event: dict[str, Any]) -> str:
    event_id = event.get("id", "")
    # T5.7：每个 SSE 事件都带产生该事件的请求 ID，便于端到端追踪。
    data = dict(event)
    rid = request_id_var.get()
    if rid:
        data.setdefault("request_id", rid)
    payload = json.dumps(data, ensure_ascii=False)
    # 事件类型放在 JSON 的 type 字段里；SSE 统一用默认 message 事件，
    # 否则 EventSource.onmessage 收不到命名事件（此前导致前端一直转圈）。
    return f"id: {event_id}\ndata: {payload}\n\n"


def _publish(turn_id: str, event: dict[str, Any]) -> None:
    with _lock:
        queues = list(_turn_queues.get(turn_id, ()))
    payload = _sse(event)
    for item in queues:
        item.put(payload)


class ConversationCreate(BaseModel):
    title: str = "新对话"
    unit_id: str | None = None


class TurnCreate(BaseModel):
    content: str
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = "default"


@router.get("/api/projects/{project_id}/conversations")
def list_conversations(project_id: str, request: Request, unit_id: str | None = None):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.conversations.list(project_id, unit_id=unit_id)


@router.post("/api/projects/{project_id}/conversations", status_code=201)
def post_conversation(project_id: str, data: ConversationCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        if data.unit_id:
            unit = uow.units.get(data.unit_id)
            if unit.project_id != project_id:
                from app.store.repositories import NotFoundError

                raise NotFoundError(data.unit_id)
        return uow.conversations.create(project_id, data.unit_id, data.title)


@router.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.conversations.get(conversation_id)


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.conversations.delete(conversation_id)
    return {"ok": True}


@router.post("/api/conversations/{conversation_id}/turns", status_code=201)
def post_turn(conversation_id: str, data: TurnCreate, request: Request):
    content = data.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    database = request.app.state.database
    with UnitOfWork(database) as uow:
        conversation = uow.conversations.get(conversation_id)
        user_message = uow.conversations.add_message(conversation_id, "user", content)
        turn = uow.agent_turns.create(
            conversation_id,
            conversation["project_id"],
            conversation.get("unit_id"),
            data.context_refs,
        )
        uow.agent_turns.set_messages(turn["id"], user_message_id=user_message["id"])
    settings = request.app.state.settings
    job_engine = get_job_engine(request.app)
    request_id = getattr(request.state, "request_id", "")

    def _run_turn_thread():
        request_id_var.set(request_id)
        run_turn(
            database,
            settings,
            job_engine,
            turn["id"],
            lambda event: _publish(turn["id"], event),
            request_id=request_id,
        )

    thread = threading.Thread(
        target=_run_turn_thread,
        name=f"agent-turn-{turn['id'][:8]}",
        daemon=True,
    )
    thread.start()
    from app.application.agent.compaction import maybe_compact_conversation

    maybe_compact_conversation(database, job_engine, conversation_id)
    return {"turn_id": turn["id"], "user_message": user_message}


@router.get("/api/conversations/{conversation_id}/stream")
def stream_turn(
    conversation_id: str,
    request: Request,
    turn_id: str,
    last_event_id: str | None = None,
):
    database = request.app.state.database
    turn_queue: queue.Queue = queue.Queue()
    with _lock:
        _turn_queues.setdefault(turn_id, set()).add(turn_queue)

    def event_source():
        try:
            last_seq = 0
            if last_event_id and ":" in last_event_id:
                try:
                    last_seq = int(last_event_id.split(":")[-1])
                except ValueError:
                    last_seq = 0
            with UnitOfWork(database) as uow:
                turn = uow.agent_turns.get(turn_id)
                for step in turn.get("steps") or []:
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
                                    step.get("arguments") or {}, ensure_ascii=False
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
                for entity in turn.get("created_entities") or []:
                    yield _sse(
                        {
                            "id": f"{turn_id}:{last_seq + 1}",
                            "type": "entity",
                            "entity": entity,
                        }
                    )
                status = turn.get("status")
                if status in ("succeeded", "failed", "canceled"):
                    yield _sse(
                        {
                            "id": f"{turn_id}:done",
                            "type": "done",
                            "failed": status == "failed",
                            "canceled": status == "canceled",
                        }
                    )
                    return
            while True:
                try:
                    item = turn_queue.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                yield item
                if '"type": "done"' in item or '"type":"done"' in item:
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/turns/{turn_id}/cancel")
def cancel_turn(turn_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        turn = uow.agent_turns.get(turn_id)
        if turn["status"] == "running":
            uow.agent_turns.set_status(turn_id, "canceled")
    return {"ok": True}


@router.post("/api/turns/{turn_id}/revert")
def revert_turn(turn_id: str, request: Request):
    return revert_agent_turn(request.app.state.database, turn_id)


@router.get("/api/turns/{turn_id}")
def get_turn(turn_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.agent_turns.get(turn_id)
