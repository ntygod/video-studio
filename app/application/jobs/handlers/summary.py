"""摘要类轻量 LLM job：单元连贯性摘要 / 对话滚动摘要（T3.3）。"""

from __future__ import annotations

from app.integrations.llm import LLMClient
from app.store import UnitOfWork

from ..context import JobContext


def _provider(uow):
    from app.application.providers import provider_for_capability

    return provider_for_capability(uow, "llm")


def run(ctx: JobContext) -> None:
    payload = ctx.job.get("payload") or {}
    task = payload.get("task")
    if task == "continuity_summary":
        _continuity_summary(ctx, payload)
    elif task == "conversation_summary":
        _conversation_summary(ctx, payload)
    else:
        raise ValueError(f"unknown summary task: {task}")
    with UnitOfWork(ctx.database) as uow:
        uow.jobs.add_event(ctx.job["id"], "摘要已生成", stage="summary", progress=0.8)
        uow.jobs.update_state(ctx.job["id"], "running", progress=0.8)


def _continuity_summary(ctx: JobContext, payload: dict) -> None:
    from app.application.agent.compaction import build_unit_summary_prompt
    from app.domain import CreativeUnit

    unit_id = payload["unit_id"]
    with UnitOfWork(ctx.database) as uow:
        unit = uow.units.get(unit_id)
        artifacts = uow.artifacts.list(unit.project_id, unit_id=unit_id)
        provider = _provider(uow)
    messages = build_unit_summary_prompt(
        unit.model_dump(mode="json"),
        artifacts,
    )
    response = LLMClient(provider).chat_json(messages)
    summary_text = str(
        response.get("final") or response.get("summary") or ""
    ).strip()
    if not summary_text:
        raise ValueError("continuity summary 为空")
    with UnitOfWork(ctx.database) as uow:
        unit = uow.units.get(unit_id)
        uow.units.update(
            CreativeUnit.model_validate(
                {
                    **unit.model_dump(mode="json"),
                    "continuity_summary": summary_text,
                }
            )
        )


def _conversation_summary(ctx: JobContext, payload: dict) -> None:
    from app.application.agent.compaction import (
        CONVERSATION_COMPACT_BATCH,
        build_conversation_summary_prompt,
    )

    conversation_id = payload["conversation_id"]
    with UnitOfWork(ctx.database) as uow:
        conversation = uow.conversations.get(conversation_id)
        messages = uow.conversations.list_messages(conversation_id)
        active = [message for message in messages if message["role"] != "compacted"]
        provider = _provider(uow)
    oldest = active[:CONVERSATION_COMPACT_BATCH]
    if len(oldest) < 2:
        raise ValueError("没有足够消息可压缩")
    prompt_messages = build_conversation_summary_prompt(conversation, oldest)
    response = LLMClient(provider).chat_json(prompt_messages)
    summary_text = str(response.get("final") or response.get("summary") or "").strip()
    if not summary_text:
        raise ValueError("conversation summary 为空")
    with UnitOfWork(ctx.database) as uow:
        for message in oldest:
            uow.conversations.set_role(message["id"], "compacted")
        uow.conversations.add_message(
            conversation_id, "system", "[滚动摘要] " + summary_text
        )
