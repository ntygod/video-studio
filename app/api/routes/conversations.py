from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.application.conversations import send_message
from app.store import UnitOfWork

router = APIRouter(tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "新对话"
    unit_id: str | None = None


class MessageCreate(BaseModel):
    content: str


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


@router.post("/api/conversations/{conversation_id}/messages")
def post_message(conversation_id: str, data: MessageCreate, request: Request):
    if not data.content.strip():
        from fastapi import HTTPException

        raise HTTPException(400, "消息不能为空")
    return send_message(request.app.state.database, conversation_id, data.content)
