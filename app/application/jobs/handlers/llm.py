"""LLM Job handler with durable, idempotent Artifact persistence."""

import json

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedArtifactCommand,
    generated_artifact_attempt,
)
from app.integrations.llm import LLMClient
from app.store import UnitOfWork

from ..context import JobContext


def _provider(uow, capability: str):
    for provider in uow.providers.list():
        if (
            provider["capability_type"] == capability
            and provider["enabled"]
        ):
            return uow.providers.get(
                provider["id"],
                include_secret=True,
            )
    raise RuntimeError(f"没有启用的 {capability} 渠道")


def _complete_persistence(
    ctx: JobContext,
    artifact: dict,
) -> None:
    version = artifact.get("current_version") or {}
    normalized = version.get("payload") or {}
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.8,
            result={
                "artifact_id": artifact["id"],
                "version_id": version.get("id"),
                "payload": normalized,
            },
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"已生成 Artifact {artifact['id']}",
            stage="llm",
            progress=0.8,
        )


def run(ctx: JobContext) -> None:
    from ..engine import JobCanceled

    if ctx.should_cancel():
        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    prompt = str(payload.get("prompt") or "")
    schema_id = str(payload.get("schema_id") or "freeform")
    artifact_kind = str(
        payload.get("artifact_kind") or "generated"
    )
    artifact_name = str(
        payload.get("artifact_name") or "AI 生成"
    )
    context = payload.get("context") or {}

    # The Artifact transaction may have committed before a process died while
    # updating the Job result. Reuse it before making another non-deterministic
    # model call.
    existing, idempotency_key = generated_artifact_attempt(
        ctx.database,
        ctx.job["id"],
    )
    if existing is not None:
        _complete_persistence(ctx, existing)
        return

    with UnitOfWork(ctx.database) as uow:
        provider = _provider(uow, "llm")
        job = uow.jobs.get(ctx.job["id"])
        project_id = job["project_id"]
        unit_id = job["unit_id"]
    messages = [{"role": "system", "content": prompt}]
    messages.append(
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False),
        }
    )
    response = LLMClient(provider).chat_json(messages)
    if ctx.should_cancel():
        raise JobCanceled()

    execution = CommandBus(ctx.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project_id,
            unit_id=unit_id,
            kind=artifact_kind,
            name=artifact_name,
            schema_id=schema_id,
            payload=response,
            source="job",
        ),
        CommandContext(
            actor_type="job",
            actor_id=ctx.job["id"],
            request_id=str(payload.get("_request_id") or ""),
            turn_id=str(job.get("turn_id") or ""),
            idempotency_key=idempotency_key,
        ),
    )
    _complete_persistence(ctx, execution.result)
