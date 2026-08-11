from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.artifacts import (
    accept_proposal,
    preview_proposal,
    reject_proposal,
)
from app.store import UnitOfWork

router = APIRouter(tags=["proposals"])


class ProposalAccept(BaseModel):
    op_indices: list[int] | None = Field(default=None)


@router.get("/api/projects/{project_id}/proposals")
def list_proposals(
    project_id: str,
    request: Request,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.proposals.list_page(
            project_id, status=status, limit=limit, cursor=cursor
        )


@router.get("/api/proposals/{proposal_id}/preview")
def preview(proposal_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return preview_proposal(uow, proposal_id)


@router.post("/api/proposals/{proposal_id}/accept")
def accept(proposal_id: str, data: ProposalAccept, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        unit_id = uow.proposals.get(proposal_id).get("unit_id")
        result = accept_proposal(uow, proposal_id, op_indices=data.op_indices)
    _dispatch_unit_summary(unit_id, request)
    return result


def _dispatch_unit_summary(unit_id: str | None, request: Request) -> None:
    """稿件采纳后异步刷新单元的 continuity_summary（T3.3）。

    尽力而为：结构提案可能已经把这个单元删掉了，摘要刷新失败不应该让采纳请求报错。
    """
    if not unit_id:
        return
    from app.application.agent.compaction import ensure_unit_summary
    from app.application.job_engine import get_job_engine

    try:
        ensure_unit_summary(
            request.app.state.database,
            get_job_engine(request.app),
            unit_id,
        )
    except Exception:
        pass


@router.post("/api/proposals/{proposal_id}/reject")
def reject(proposal_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return reject_proposal(uow, proposal_id)

