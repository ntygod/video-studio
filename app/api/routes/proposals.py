from fastapi import APIRouter, Request

from app.application.artifacts import accept_proposal, reject_proposal
from app.store import UnitOfWork

router = APIRouter(tags=["proposals"])


@router.get("/api/projects/{project_id}/proposals")
def list_proposals(project_id: str, request: Request, status: str | None = None):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.proposals.list(project_id, status=status)


@router.post("/api/proposals/{proposal_id}/accept")
def accept(proposal_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return accept_proposal(uow, proposal_id)


@router.post("/api/proposals/{proposal_id}/reject")
def reject(proposal_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return reject_proposal(uow, proposal_id)

