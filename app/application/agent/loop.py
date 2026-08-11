from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.integrations.llm import build_adapter
from app.application.providers import provider_for_capability
from app.store import UnitOfWork

from .context import build_initial_context
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_BY_NAME, TOOLS, ToolContext

MAX_STEPS = 12

#: 流式输出期间检查取消的最小间隔。每个 token 都查库太贵，完全不查又会让
#: 「停止」在模型长输出时迟迟不生效。
CANCEL_PROBE_INTERVAL = 1.0


def _make_cancel_probe(database, turn_id: str) -> Callable[[], bool]:
    """节流的取消探针：最多每 CANCEL_PROBE_INTERVAL 秒查一次库，命中后固定返回 True。"""
    state = {"checked_at": 0.0, "canceled": False}

    def probe() -> bool:
        if state["canceled"]:
            return True
        now = time.monotonic()
        if now - state["checked_at"] < CANCEL_PROBE_INTERVAL:
            return False
        state["checked_at"] = now
        try:
            with UnitOfWork(database) as uow:
                state["canceled"] = uow.agent_turns.get(turn_id)["status"] == "canceled"
        except Exception:
            state["canceled"] = False
        return state["canceled"]

    return probe


def _llm_provider(uow):
    return provider_for_capability(uow, "llm")


def _preview(args: dict[str, Any]) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text[:80] + ("…" if len(text) > 80 else "")


def _summarize(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name == "read_unit":
        unit = result.get("unit") or {}
        return f"读取 {unit.get('title', '单元')}"
    if tool_name == "read_artifact":
        return f"读取稿件 {result.get('path') or '摘要'}"
    if tool_name == "write_artifact":
        return f"写入稿件 {result.get('artifact_id', '')[:8]}"
    if tool_name == "create_units":
        return f"创建 {len(result.get('units') or [])} 个单元"
    if tool_name == "generate_media":
        return f"派发任务 {result.get('job_id', '')[:8]}"
    if tool_name == "propose_change":
        return f"提案 {result.get('proposal_id', '')[:8]}"
    if tool_name == "propose_restructure":
        return f"结构提案 {result.get('proposal_id', '')[:8]}"
    return f"{tool_name} 完成"


def _done_event(
    seq: dict[str, int],
    ev: Callable[[dict[str, Any]], None],
    message_id: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    canceled: bool = False,
    failed: bool = False,
) -> None:
    ev(
        {
            "type": "done",
            "message_id": message_id,
            "usage": {"prompt": prompt_tokens, "completion": completion_tokens},
            "canceled": canceled,
            "failed": failed,
        }
    )
def run_turn(
    database,
    settings,
    job_engine,
    turn_id: str,
    emit: Callable[[dict[str, Any]], None],
    request_id: str = "",
) -> None:
    """读取 turn → 组装上下文 → 循环调用 LLM 与工具 → 落库 → emit 事件。

    每一步都检查 turn.status 是否被置为 canceled（协作式中断）。
    """
    seq_counter = {"n": 0}

    def ev(event: dict[str, Any]) -> None:
        seq_counter["n"] += 1
        emit(
            {
                "id": f"{turn_id}:{seq_counter['n']}",
                "seq": seq_counter["n"],
                "request_id": request_id,
                **event,
            }
        )

    prompt_tokens = 0
    completion_tokens = 0
    try:
        with UnitOfWork(database) as uow:
            turn = uow.agent_turns.get(turn_id)
            if turn["status"] != "running":
                return
            conversation = uow.conversations.get(turn["conversation_id"])
            project_id = turn["project_id"]
            unit_id = turn.get("unit_id")
            conversation_id = turn["conversation_id"]
            provider = _llm_provider(uow)
            context_text, _ = build_initial_context(
                uow, project_id, unit_id, turn.get("context_refs")
            )
            history = uow.conversations.list_messages(conversation_id)
            current_user = next(
                (message for message in history if message["id"] == turn.get("user_message_id")),
                None,
            )
            if current_user is None:
                raise RuntimeError("turn 缺少用户消息")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context_text}
        ]
        for message in history:
            if message["id"] == turn.get("user_message_id"):
                continue
            if message["role"] in ("user", "assistant", "system"):
                messages.append({"role": message["role"], "content": message["content"]})
        messages.append({"role": "user", "content": current_user["content"]})

        adapter = build_adapter(provider)
        cancel_probe = _make_cancel_probe(database, turn_id)
        steps = 0
        final_text = ""
        while True:
            with UnitOfWork(database) as uow:
                status = uow.agent_turns.get(turn_id)["status"]
            if status == "canceled":
                _done_event(seq_counter, ev, None, prompt_tokens, completion_tokens, canceled=True)
                return
            if status != "running":
                return
            if steps >= MAX_STEPS:
                final_text = "已达到单回合最大步数，请继续追问。"
                break
            tool_calls = []
            text_parts: list[str] = []
            canceled_mid_stream = False
            try:
                stream = adapter.stream(messages, [tool.spec for tool in TOOLS])
                try:
                    for chunk in stream:
                        # 模型长输出时也要能停下来，否则「停止」要等整段流结束才生效。
                        if cancel_probe():
                            canceled_mid_stream = True
                            break
                        if chunk.kind == "token":
                            text_parts.append(chunk.text)
                            ev({"type": "token", "text": chunk.text})
                        elif chunk.kind == "tool_call":
                            tool_calls.append(chunk.tool_call)
                        elif chunk.kind == "usage" and chunk.usage:
                            prompt_tokens += int(chunk.usage.get("prompt_tokens") or 0)
                            completion_tokens += int(chunk.usage.get("completion_tokens") or 0)
                finally:
                    # 提前 break 时显式关掉生成器，让底层 httpx 连接立即释放。
                    close = getattr(stream, "close", None)
                    if close:
                        close()
            except Exception as exc:
                raise RuntimeError(f"LLM 调用失败：{exc}") from exc
            if canceled_mid_stream:
                _done_event(seq_counter, ev, None, prompt_tokens, completion_tokens, canceled=True)
                return
            if not tool_calls:
                final_text = "".join(text_parts).strip()
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                with UnitOfWork(database) as uow:
                    status = uow.agent_turns.get(turn_id)["status"]
                if status == "canceled":
                    _done_event(seq_counter, ev, None, prompt_tokens, completion_tokens, canceled=True)
                    return
                tool = TOOL_BY_NAME.get(call.name)
                with UnitOfWork(database) as uow:
                    step = uow.agent_turns.add_step(
                        turn_id,
                        "tool",
                        tool_name=call.name,
                        arguments=call.arguments,
                        request_id=request_id,
                    )
                ev(
                    {
                        "type": "step.start",
                        "step_id": step["id"],
                        "tool": call.name,
                        "args_preview": _preview(call.arguments),
                    }
                )
                result: dict[str, Any] = {}
                ok = False
                summary = ""
                error_text = ""
                if tool is None:
                    error_text = f"未知工具：{call.name}"
                else:
                    try:
                        with UnitOfWork(database) as uow:
                            ctx = ToolContext(
                                uow, project_id, unit_id, turn_id, settings, job_engine
                            )
                            result = tool.handler(ctx, call.arguments)
                        ok = True
                        summary = _summarize(call.name, result)
                        for entity in result.get("entities") or []:
                            with UnitOfWork(database) as uow:
                                uow.agent_turns.record_entity(turn_id, entity["type"], entity["id"])
                            ev({"type": "entity", "entity": entity})
                    except Exception as exc:
                        error_text = f"工具执行失败：{exc}"
                        summary = str(exc)[:120]
                with UnitOfWork(database) as uow:
                    finished = uow.agent_turns.finish_step(
                        step["id"],
                        "ok" if ok else "failed",
                        result=result if ok else None,
                        summary=summary,
                        error=error_text,
                    )
                ev(
                    {
                        "type": "step.done",
                        "step_id": step["id"],
                        "ok": ok,
                        "duration_ms": finished["duration_ms"],
                        "summary": summary,
                    }
                )
                if not ok:
                    ev({"type": "error", "message": error_text, "recoverable": True})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result if ok else {"error": error_text}, ensure_ascii=False)[:4000],
                    }
                )
            steps += 1
        if not final_text:
            final_text = "已完成。"
        with UnitOfWork(database) as uow:
            assistant_message = uow.conversations.add_message(
                conversation_id, "assistant", final_text
            )
            uow.agent_turns.set_messages(turn_id, assistant_message_id=assistant_message["id"])
            uow.agent_turns.set_usage(turn_id, prompt_tokens, completion_tokens)
            uow.agent_turns.set_status(turn_id, "succeeded")
        _done_event(
            seq_counter, ev, assistant_message["id"], prompt_tokens, completion_tokens
        )
    except Exception as exc:
        error_text = str(exc)
        try:
            with UnitOfWork(database) as uow:
                turn = uow.agent_turns.get(turn_id)
                step = uow.agent_turns.add_step(
                    turn_id,
                    "error",
                    arguments={"error": error_text},
                    request_id=request_id,
                )
                uow.agent_turns.finish_step(
                    step["id"], "failed", summary=error_text[:120], error=error_text
                )
                uow.agent_turns.set_status(turn_id, "failed", error=error_text)
                try:
                    assistant_message = uow.conversations.add_message(
                        turn["conversation_id"], "assistant", f"执行失败：{error_text}"
                    )
                    uow.agent_turns.set_messages(
                        turn_id, assistant_message_id=assistant_message["id"]
                    )
                except Exception:
                    pass
        except Exception:
            pass
        ev({"type": "error", "message": error_text, "recoverable": False})
        _done_event(seq_counter, ev, None, prompt_tokens, completion_tokens, failed=True)
