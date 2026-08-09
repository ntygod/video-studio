from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.providers import model_capabilities
from app.store import UnitOfWork

router = APIRouter(tags=["providers"])


class ModelCreate(BaseModel):
    name: str = ""
    model_id: str
    capability_type: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class ProviderCreate(BaseModel):
    name: str
    capability_type: str
    adapter: str
    base_url: str = ""
    api_key: str = ""
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    models: list[ModelCreate] = Field(default_factory=list)


class ProviderPatch(BaseModel):
    name: str | None = None
    capability_type: str | None = None
    adapter: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    settings: dict[str, Any] | None = None


@router.get("/api/provider-profiles")
def list_provider_profiles(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.list()


@router.post("/api/provider-profiles", status_code=201)
def post_provider_profile(data: ProviderCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.create(data.model_dump())


@router.get("/api/provider-profiles/{provider_id}")
def get_provider_profile(provider_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.get(provider_id)


@router.patch("/api/provider-profiles/{provider_id}")
def patch_provider_profile(provider_id: str, data: ProviderPatch, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.update(provider_id, data.model_dump(exclude_none=True))


@router.delete("/api/provider-profiles/{provider_id}")
def delete_provider_profile(provider_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.providers.delete(provider_id)
    return {"ok": True}


@router.get("/api/model-capabilities")
def get_model_capabilities(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return model_capabilities(uow)

