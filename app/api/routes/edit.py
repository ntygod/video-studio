from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.application.ai_edit import generate_edit_plan

router = APIRouter(tags=["edit"])


class EditPlanRequest(BaseModel):
    unit_id: str | None = None


@router.post("/api/projects/{project_id}/edit-plan")
def create_edit_plan(project_id: str, data: EditPlanRequest, request: Request):
    return generate_edit_plan(request.app.state.database, project_id, data.unit_id)
