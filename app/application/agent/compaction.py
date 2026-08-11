"""上下文压缩（T3.3）。

- 单元连贯性摘要：稿件被采纳/定稿时派发轻量 llm job 刷新 continuity_summary。
- 对话滚动摘要：超过阈值后把最旧的若干轮压缩成一条 system 摘要消息，
  原消息标记为 compacted，不再进入 LLM 上下文。

所有函数都自管理事务：先落库 job，再 submit 引擎，避免未提交的数据
在 worker 线程里不可见。
"""

from __future__ import annotations

from typing import Any

from app.store import UnitOfWork

# 约 20 轮对话 = 40 条消息；一次压缩最旧的 10 轮（20 条）
CONVERSATION_COMPACT_THRESHOLD = 40
CONVERSATION_COMPACT_BATCH = 20

_ACTIVE_STATUSES = ("queued", "running")


def _has_active_job(
    uow: UnitOfWork, scope_key: str, task: str
) -> bool:
    for job in uow.jobs.list():
        payload = job.get("payload") or {}
        if payload.get("task") != task:
            continue
        if job["status"] not in _ACTIVE_STATUSES:
            continue
        if task == "conversation_summary":
            if payload.get("conversation_id") == scope_key:
                return True
        elif payload.get("unit_id") == scope_key:
            return True
    return False


def ensure_unit_summary(database, job_engine, unit_id: str) -> None:
    """单元稿件被采纳/定稿后刷新 2–3 句连贯性摘要（幂等去重）。"""
    with UnitOfWork(database) as uow:
        unit = uow.units.get(unit_id)
        if _has_active_job(uow, unit_id, "continuity_summary"):
            return
        job = uow.jobs.create(
            {
                "project_id": unit.project_id,
                "unit_id": unit_id,
                "job_type": "summary",
                "payload": {"task": "continuity_summary", "unit_id": unit_id},
            }
        )
    job_engine.submit(job["id"])


def maybe_compact_conversation(database, job_engine, conversation_id: str) -> None:
    """消息数超过阈值时派发对话滚动摘要任务。"""
    with UnitOfWork(database) as uow:
        conversation = uow.conversations.get(conversation_id)
        messages = uow.conversations.list_messages(conversation_id)
        active = [message for message in messages if message["role"] != "compacted"]
        if len(active) < CONVERSATION_COMPACT_THRESHOLD:
            return
        if _has_active_job(uow, conversation_id, "conversation_summary"):
            return
        job = uow.jobs.create(
            {
                "project_id": conversation["project_id"],
                "unit_id": conversation.get("unit_id"),
                "job_type": "summary",
                "payload": {
                    "task": "conversation_summary",
                    "conversation_id": conversation_id,
                },
            }
        )
    job_engine.submit(job["id"])


def _compact_payload_text(payload: dict[str, Any], limit: int = 600) -> str:
    import json

    text = json.dumps(payload, ensure_ascii=False)
    return text[:limit] + ("…" if len(text) > limit else "")


def build_unit_summary_prompt(unit: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for artifact in artifacts[:3]:
        version = artifact.get("current_version") or {}
        rows.append(
            f"- {artifact['kind']}「{artifact['name']}」v{version.get('version', 1)}："
            + _compact_payload_text(version.get("payload") or {}, 800)
        )
    return [
        {
            "role": "system",
            "content": (
                "你是视频工作室的连续性管理员。请用 2–3 句中文概括这个创作单元的"
                "核心设定、已完成内容与尚未落地的方向，供后续创作参考。"
                "只输出 JSON：{\"final\": \"摘要\"}。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"单元：{unit.get('title', '')}（{unit.get('unit_type', '')}）\n"
                f"已有摘要：{unit.get('continuity_summary') or '（无）'}\n"
                f"稿件：\n" + "\n".join(rows)
            ),
        },
    ]


def build_conversation_summary_prompt(
    conversation: dict[str, Any], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lines = [
        f"{message['role']}：{message['content'][:300]}"
        for message in messages
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是对话压缩器。把下面这段创作对话浓缩成 3–5 句中文摘要，"
                "保留已确认的决定、用户偏好与待办。只输出 JSON：{\"final\": \"摘要\"}。"
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]
