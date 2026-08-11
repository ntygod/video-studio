"""LLM job handler：把一次 chat_json 的结果落成 artifact。"""

import json

from app.integrations.llm import LLMClient
from app.store import UnitOfWork

from ..context import JobContext


def _provider(uow, capability: str):
    for provider in uow.providers.list():
        if provider["capability_type"] == capability and provider["enabled"]:
            return uow.providers.get(provider["id"], include_secret=True)
    raise RuntimeError(f"没有启用的 {capability} 渠道")


def run(ctx: JobContext) -> None:
    if ctx.should_cancel():
        from ..engine import JobCanceled

        raise JobCanceled()
    payload = ctx.job.get("payload") or {}
    prompt = str(payload.get("prompt") or "")
    schema_id = str(payload.get("schema_id") or "freeform")
    artifact_kind = payload.get("artifact_kind") or "generated"
    artifact_name = payload.get("artifact_name") or "AI 生成"
    context = payload.get("context") or {}
    with UnitOfWork(ctx.database) as uow:
        provider = _provider(uow, "llm")
        project_id = ctx.job["project_id"]
        unit_id = ctx.job["unit_id"]
    messages = [{"role": "system", "content": prompt}]
    messages.append(
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
    )
    response = LLMClient(provider).chat_json(messages)
    if ctx.should_cancel():
        from ..engine import JobCanceled

        raise JobCanceled()
    with UnitOfWork(ctx.database) as uow:
        # 制作流程产物在同一作用域只有一份身份；重新生成应追加版本，
        # 否则交付页会堆出多份都叫“第 1 版”的剪辑计划。
        artifact = None
        if artifact_kind in {"edit_plan", "timeline"}:
            artifact = uow.artifacts.find_latest(project_id, unit_id, artifact_kind)
        if artifact:
            uow.artifacts.add_version(
                artifact["id"],
                response,
                source="job",
                note=f"重新生成{artifact_name}",
            )
            artifact = uow.artifacts.get(artifact["id"])
        else:
            artifact = uow.artifacts.create(
                project_id=project_id,
                unit_id=unit_id,
                kind=artifact_kind,
                name=artifact_name,
                schema_id=schema_id,
                payload=response,
                source="job",
            )
        uow.jobs.update_state(
            ctx.job["id"],
            "running",
            progress=0.8,
            result={"artifact_id": artifact["id"], "payload": response},
        )
        uow.jobs.add_event(
            ctx.job["id"],
            f"已生成 Artifact {artifact['id']}",
            stage="llm",
            progress=0.8,
        )
