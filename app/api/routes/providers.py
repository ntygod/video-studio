from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.application.providers import (
    ProviderDiscoveryError,
    discover_provider_models,
    model_capabilities,
)
from app.integrations.provider_http import provider_endpoint, provider_headers
from app.store import UnitOfWork

router = APIRouter(tags=["providers"])


class ModelCreate(BaseModel):
    name: str = ""
    model_id: str
    capability_type: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


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
    models: list[ModelCreate] | None = None


class ProviderDiscoveryRequest(BaseModel):
    provider_id: str | None = None
    capability_type: str = "llm"
    adapter: str = "openai"
    base_url: str = ""
    api_key: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/provider-profiles")
def list_provider_profiles(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.list()


@router.post("/api/provider-profiles", status_code=201)
def post_provider_profile(data: ProviderCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.providers.create(data.model_dump())


@router.post("/api/provider-profiles/discover-models")
def discover_models(data: ProviderDiscoveryRequest, request: Request):
    supplied = data.model_dump(exclude={"provider_id"})
    if data.provider_id:
        with UnitOfWork(request.app.state.database) as uow:
            saved = uow.providers.get(data.provider_id, include_secret=True)
        provider = {
            **saved,
            **supplied,
            "base_url": data.base_url.strip() or saved["base_url"],
            "api_key": data.api_key or saved["api_key"],
            "adapter": data.adapter or saved["adapter"],
        }
    else:
        provider = supplied
    try:
        return discover_provider_models(provider)
    except ProviderDiscoveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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


@router.post("/api/provider-profiles/{provider_id}/test")
def test_provider_profile(provider_id: str, request: Request):
    import time

    import httpx

    with UnitOfWork(request.app.state.database) as uow:
        provider = uow.providers.get(provider_id, include_secret=True)
    from app.application.providers import _normalized_capability

    capability = _normalized_capability(provider.get("capability_type"))
    models = [
        model
        for model in (provider.get("models") or [])
        if _normalized_capability(model.get("capability_type") or capability) == capability
    ] or (provider.get("models") or [])
    provider["models"] = models
    model_id = models[0]["model_id"] if models else "default"
    start = time.monotonic()
    try:
        if capability == "llm":
            response = httpx.post(
                provider_endpoint(provider, "chat/completions", "chat_path"),
                headers=provider_headers(provider),
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=15,
            )
            response.raise_for_status()
        else:
            response = httpx.get(
                provider_endpoint(provider, "models", "models_path"),
                headers=provider_headers(provider),
                timeout=15,
            )
            response.raise_for_status()
        return {
            "ok": True,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "detail": "连接正常",
            "models_seen": [item["model_id"] for item in models],
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "detail": str(exc),
            "models_seen": [item["model_id"] for item in models],
        }


@router.get("/api/model-capabilities")
def get_model_capabilities(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return model_capabilities(uow)

