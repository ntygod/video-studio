"""Checkpointed Agent tool loop for the generic durable task runtime."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any, Callable

from app.application.providers import provider_for_capability
from app.application.task_runtime_engine import (
    TaskExecutionCanceled,
    TaskExecutionContext,
)
from app.integrations.llm import build_adapter
from app.store import UnitOfWork
from app.store.repositories import ConflictError
from app.store.task_runtime_models import RuntimeTaskRow

from .context import build_initial_context
from .durable_steps import ensure_tool_step
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_BY_NAME, TOOLS, ToolContext

AGENT_PLAN_KIND = "agent.turn"
AGENT_TASK_TYPE = "agent.turn.execute"
CHECKPOINT_VERSION = 1
MAX_STEPS = 12

LiveEmitter = Callable[[dict[str, Any]], None]
FaultHook = Callable[[str, dict[str, Any]], None]


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


def _fault(
    hook: FaultHook | None,
    point: str,
    payload: dict[str, Any],
) -> None:
    if hook is not None:
        hook(point, payload)


def _logical_call_id(
    round_index: int,
    call_index: int,
    provider_call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> str:
    identity = json.dumps(
        {
            "round": round_index,
            "index": call_index,
            "provider_call_id": provider_call_id,
            "name": name,
            "arguments": arguments,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:20]
    return f"round-{round_index}:call-{call_index}:{digest}"


def _event(
    context: TaskExecutionContext,
    turn_id: str,
    live_emit: LiveEmitter | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    stored = context.emit(
        f"agent.{event['type']}",
        {"turn_id": turn_id, **deepcopy(event)},
    )
    emitted = {
        "id": f"{turn_id}:{stored['seq']}",
        "seq": stored["seq"],
        **event,
    }
    if live_emit is not None:
        live_emit(emitted)
    return emitted


def _live_token(
    live_emit: LiveEmitter | None,
    turn_id: str,
    token_index: int,
    text: str,
) -> None:
    if live_emit is None:
        return
    live_emit(
        {
            "id": f"{turn_id}:live:{token_index}",
            "type": "token",
            "text": text,
            "durable": False,
        }
    )


def _usage(checkpoint: dict[str, Any]) -> dict[str, int]:
    return {
        "prompt_tokens": int(checkpoint.get("prompt_tokens") or 0),
        "completion_tokens": int(
            checkpoint.get("completion_tokens") or 0
        ),
    }


def _persist(
    context: TaskExecutionContext,
    checkpoint: dict[str, Any],
) -> None:
    context.heartbeat(
        checkpoint=deepcopy(checkpoint),
        usage=_usage(checkpoint),
    )


def _initial_checkpoint(
    database,
    turn_id: str,
    *,
    adapter_override: bool,
) -> dict[str, Any]:
    with UnitOfWork(database) as uow:
        turn = uow.agent_turns.get(turn_id)
        if turn["status"] == "canceled":
            raise TaskExecutionCanceled("Agent turn was canceled")
        if turn["status"] == "failed":
            raise RuntimeError(turn.get("error") or "Agent turn failed")
        conversation = uow.conversations.get(turn["conversation_id"])
        context_text, _ = build_initial_context(
            uow,
            turn["project_id"],
            turn.get("unit_id"),
            turn.get("context_refs"),
        )
        history = uow.conversations.list_messages(
            turn["conversation_id"]
        )
        current_user = next(
            (
                message
                for message in history
                if message["id"] == turn.get("user_message_id")
            ),
            None,
        )
        if current_user is None:
            raise RuntimeError("turn 缺少用户消息")
        provider_id = ""
        model_id = ""
        if not adapter_override:
            provider = provider_for_capability(uow, "llm")
            provider_id = str(provider["id"])
            models = provider.get("models") or []
            model_id = str(
                (models[0] if models else {}).get("model_id") or ""
            )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n" + context_text,
        }
    ]
    for message in history:
        if message["id"] == turn.get("user_message_id"):
            continue
        if message["role"] in ("user", "assistant", "system"):
            messages.append(
                {
                    "role": message["role"],
                    "content": message["content"],
                }
            )
    messages.append(
        {"role": "user", "content": current_user["content"]}
    )
    return {
        "version": CHECKPOINT_VERSION,
        "turn_id": turn_id,
        "conversation_id": conversation["id"],
        "project_id": turn["project_id"],
        "unit_id": turn.get("unit_id"),
        "provider_id": provider_id,
        "model_id": model_id,
        "phase": "model",
        "round": 0,
        "messages": messages,
        "tool_calls": [],
        "tool_index": 0,
        "prompt_tokens": int(turn.get("prompt_tokens") or 0),
        "completion_tokens": int(
            turn.get("completion_tokens") or 0
        ),
        "final_text": "",
        "assistant_message_id": turn.get("assistant_message_id"),
    }


def _adapter_for_checkpoint(database, checkpoint):
    provider_id = str(checkpoint.get("provider_id") or "")
    model_id = str(checkpoint.get("model_id") or "")
    if not provider_id:
        raise RuntimeError("Agent checkpoint has no frozen LLM provider")
    with UnitOfWork(database) as uow:
        provider = uow.providers.get(
            provider_id,
            include_secret=True,
        )
    models = list(provider.get("models") or [])
    if model_id:
        selected = [
            model
            for model in models
            if str(model.get("model_id") or "") == model_id
        ]
        if not selected:
            raise RuntimeError(
                "Agent checkpoint LLM model is no longer available"
            )
        provider["models"] = selected + [
            model for model in models if model not in selected
        ]
    return build_adapter(provider)


def _assert_turn_active(
    database,
    context: TaskExecutionContext,
    turn_id: str,
) -> dict[str, Any]:
    context.raise_if_cancelled()
    with UnitOfWork(database) as uow:
        turn = uow.agent_turns.get(turn_id)
    if turn["status"] == "canceled":
        raise TaskExecutionCanceled("Agent turn was canceled")
    if turn["status"] == "failed":
        raise RuntimeError(turn.get("error") or "Agent turn failed")
    return turn


def _execute_tool_call(
    database,
    settings,
    job_engine,
    context: TaskExecutionContext,
    checkpoint: dict[str, Any],
    call: dict[str, Any],
    *,
    request_id: str,
    live_emit: LiveEmitter | None,
    fault_hook: FaultHook | None,
) -> tuple[dict[str, Any], bool, str, str]:
    turn_id = str(checkpoint["turn_id"])
    with UnitOfWork(database) as uow:
        step = ensure_tool_step(
            uow,
            turn_id=turn_id,
            logical_call_id=str(call["logical_call_id"]),
            tool_name=str(call["name"]),
            arguments=dict(call["arguments"]),
            request_id=request_id,
        )

    _event(
        context,
        turn_id,
        live_emit,
        {
            "type": "step.start",
            "step_id": step["id"],
            "tool": call["name"],
            "args_preview": _preview(call["arguments"]),
        },
    )

    if step["status"] == "ok":
        result = dict(step.get("result") or {})
        return result, True, step.get("summary") or "", ""
    if step["status"] == "failed":
        return {}, False, step.get("summary") or "", step.get(
            "error"
        ) or "工具执行失败"
    if step["status"] != "running":
        raise ConflictError(
            f"Agent tool Step has invalid status: {step['status']}"
        )

    tool = TOOL_BY_NAME.get(str(call["name"]))
    result: dict[str, Any] = {}
    ok = False
    summary = ""
    error_text = ""
    if tool is None:
        error_text = f"未知工具：{call['name']}"
        summary = error_text
    else:
        try:
            _assert_turn_active(database, context, turn_id)
            with UnitOfWork(database) as uow:
                tool_context = ToolContext(
                    uow,
                    str(checkpoint["project_id"]),
                    checkpoint.get("unit_id"),
                    turn_id,
                    settings,
                    job_engine,
                )
                tool_context.step_id = step["id"]
                result = tool.handler(
                    tool_context,
                    dict(call["arguments"]),
                )
            ok = True
            summary = _summarize(str(call["name"]), result)
        except Exception as exc:
            error_text = f"工具执行失败：{exc}"
            summary = str(exc)[:120]

    _fault(
        fault_hook,
        "after_tool_command",
        {
            "turn_id": turn_id,
            "step_id": step["id"],
            "tool": call["name"],
            "ok": ok,
            "result": deepcopy(result),
            "error": error_text,
        },
    )

    with UnitOfWork(database) as uow:
        if ok:
            for entity in result.get("entities") or []:
                uow.agent_turns.record_entity(
                    turn_id,
                    str(entity["type"]),
                    str(entity["id"]),
                )
        finished = uow.agent_turns.finish_step(
            step["id"],
            "ok" if ok else "failed",
            result=result if ok else None,
            summary=summary,
            error=error_text,
        )

    for entity in result.get("entities") or []:
        _event(
            context,
            turn_id,
            live_emit,
            {"type": "entity", "entity": entity},
        )
    _event(
        context,
        turn_id,
        live_emit,
        {
            "type": "step.done",
            "step_id": step["id"],
            "ok": ok,
            "duration_ms": finished["duration_ms"],
            "summary": summary,
        },
    )
    if not ok:
        _event(
            context,
            turn_id,
            live_emit,
            {
                "type": "error",
                "message": error_text,
                "recoverable": True,
            },
        )
    return result, ok, summary, error_text


def _finalize_turn(
    database,
    context: TaskExecutionContext,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    turn_id = str(checkpoint["turn_id"])
    final_text = str(checkpoint.get("final_text") or "").strip()
    if not final_text:
        final_text = "已完成。"
    now = time.time()
    with UnitOfWork(database) as uow:
        task = uow.session.get(RuntimeTaskRow, context.task["id"])
        if (
            task is None
            or task.status != "running"
            or task.claim_token != context.claim["claim_token"]
            or task.claim_until is None
            or task.claim_until <= now
        ):
            raise ConflictError(
                "Agent finalization lost its RuntimeTask lease"
            )
        turn = uow.agent_turns.get(turn_id)
        if turn["status"] == "canceled":
            raise TaskExecutionCanceled("Agent turn was canceled")
        if turn["status"] == "succeeded":
            return {
                "turn_id": turn_id,
                "assistant_message_id": turn.get(
                    "assistant_message_id"
                ),
                **_usage(checkpoint),
            }
        if turn["status"] == "failed":
            raise RuntimeError(turn.get("error") or "Agent turn failed")
        assistant_message = uow.conversations.add_message(
            str(checkpoint["conversation_id"]),
            "assistant",
            final_text,
        )
        uow.agent_turns.set_messages(
            turn_id,
            assistant_message_id=assistant_message["id"],
        )
        uow.agent_turns.set_usage(
            turn_id,
            int(checkpoint.get("prompt_tokens") or 0),
            int(checkpoint.get("completion_tokens") or 0),
        )
        uow.agent_turns.set_status(turn_id, "succeeded")
    return {
        "turn_id": turn_id,
        "assistant_message_id": assistant_message["id"],
        **_usage(checkpoint),
    }


def run_durable_agent_turn(
    database,
    settings,
    job_engine,
    context: TaskExecutionContext,
    *,
    live_emit: LiveEmitter | None = None,
    request_id: str = "",
    adapter=None,
    fault_hook: FaultHook | None = None,
) -> dict[str, Any]:
    """Run or resume one Agent Turn from the RuntimeTask checkpoint."""

    turn_id = str(
        context.task.get("payload", {}).get("turn_id")
        or context.plan.get("subject_id")
        or ""
    )
    if not turn_id:
        raise RuntimeError("Agent RuntimeTask has no turn_id")

    with UnitOfWork(database) as uow:
        existing_turn = uow.agent_turns.get(turn_id)
    if existing_turn["status"] == "succeeded":
        return {
            "turn_id": turn_id,
            "assistant_message_id": existing_turn.get(
                "assistant_message_id"
            ),
            "prompt_tokens": int(
                existing_turn.get("prompt_tokens") or 0
            ),
            "completion_tokens": int(
                existing_turn.get("completion_tokens") or 0
            ),
        }
    if existing_turn["status"] == "canceled":
        raise TaskExecutionCanceled("Agent turn was canceled")
    if existing_turn["status"] == "failed":
        raise RuntimeError(
            existing_turn.get("error") or "Agent turn failed"
        )

    checkpoint = deepcopy(context.checkpoint or {})
    if not checkpoint:
        checkpoint = _initial_checkpoint(
            database,
            turn_id,
            adapter_override=adapter is not None,
        )
        _persist(context, checkpoint)
        _fault(
            fault_hook,
            "after_initial_checkpoint",
            {"turn_id": turn_id},
        )
    if (
        int(checkpoint.get("version") or 0) != CHECKPOINT_VERSION
        or checkpoint.get("turn_id") != turn_id
    ):
        raise RuntimeError("Agent RuntimeTask checkpoint is incompatible")

    llm_adapter = adapter
    token_index = 0
    while True:
        _assert_turn_active(database, context, turn_id)
        phase = str(checkpoint.get("phase") or "model")

        if phase == "done":
            return {
                "turn_id": turn_id,
                "assistant_message_id": checkpoint.get(
                    "assistant_message_id"
                ),
                **_usage(checkpoint),
            }

        if phase == "model":
            round_index = int(checkpoint.get("round") or 0)
            if round_index >= MAX_STEPS:
                checkpoint["final_text"] = (
                    "已达到单回合最大步数，请继续追问。"
                )
                checkpoint["phase"] = "finalize"
                _persist(context, checkpoint)
                continue
            if llm_adapter is None:
                llm_adapter = _adapter_for_checkpoint(
                    database,
                    checkpoint,
                )

            tool_calls = []
            text_parts: list[str] = []
            try:
                stream = llm_adapter.stream(
                    list(checkpoint["messages"]),
                    [tool.spec for tool in TOOLS],
                )
                try:
                    for chunk in stream:
                        _assert_turn_active(
                            database,
                            context,
                            turn_id,
                        )
                        if chunk.kind == "token":
                            text_parts.append(chunk.text)
                            token_index += 1
                            _live_token(
                                live_emit,
                                turn_id,
                                token_index,
                                chunk.text,
                            )
                        elif (
                            chunk.kind == "tool_call"
                            and chunk.tool_call is not None
                        ):
                            tool_calls.append(chunk.tool_call)
                        elif chunk.kind == "usage" and chunk.usage:
                            checkpoint["prompt_tokens"] = int(
                                checkpoint.get("prompt_tokens") or 0
                            ) + int(
                                chunk.usage.get("prompt_tokens") or 0
                            )
                            checkpoint["completion_tokens"] = int(
                                checkpoint.get("completion_tokens") or 0
                            ) + int(
                                chunk.usage.get("completion_tokens")
                                or 0
                            )
                finally:
                    close = getattr(stream, "close", None)
                    if close:
                        close()
            except TaskExecutionCanceled:
                raise
            except ConflictError:
                raise
            except Exception as exc:
                raise RuntimeError(f"LLM 调用失败：{exc}") from exc

            if not tool_calls:
                checkpoint["final_text"] = "".join(
                    text_parts
                ).strip()
                checkpoint["phase"] = "finalize"
                _persist(context, checkpoint)
                _fault(
                    fault_hook,
                    "after_model_checkpoint",
                    {"turn_id": turn_id, "tool_calls": 0},
                )
                continue

            serialized_calls = []
            assistant_calls = []
            for call_index, call in enumerate(tool_calls):
                arguments = deepcopy(call.arguments or {})
                logical_id = _logical_call_id(
                    round_index,
                    call_index,
                    str(call.id or ""),
                    str(call.name or ""),
                    arguments,
                )
                serialized_calls.append(
                    {
                        "logical_call_id": logical_id,
                        "provider_call_id": str(call.id or logical_id),
                        "name": str(call.name or ""),
                        "arguments": arguments,
                    }
                )
                assistant_calls.append(
                    {
                        "id": str(call.id or logical_id),
                        "type": "function",
                        "function": {
                            "name": str(call.name or ""),
                            "arguments": json.dumps(
                                arguments,
                                ensure_ascii=False,
                            ),
                        },
                    }
                )
            checkpoint["messages"].append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_calls,
                }
            )
            checkpoint["tool_calls"] = serialized_calls
            checkpoint["tool_index"] = 0
            checkpoint["phase"] = "tools"
            _persist(context, checkpoint)
            _fault(
                fault_hook,
                "after_model_checkpoint",
                {
                    "turn_id": turn_id,
                    "tool_calls": len(serialized_calls),
                },
            )
            continue

        if phase == "tools":
            calls = list(checkpoint.get("tool_calls") or [])
            index = int(checkpoint.get("tool_index") or 0)
            while index < len(calls):
                call = dict(calls[index])
                result, ok, _summary, error_text = (
                    _execute_tool_call(
                        database,
                        settings,
                        job_engine,
                        context,
                        checkpoint,
                        call,
                        request_id=request_id,
                        live_emit=live_emit,
                        fault_hook=fault_hook,
                    )
                )
                checkpoint["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": call["provider_call_id"],
                        "content": json.dumps(
                            result if ok else {"error": error_text},
                            ensure_ascii=False,
                        )[:4000],
                    }
                )
                index += 1
                checkpoint["tool_index"] = index
                _persist(context, checkpoint)
                _fault(
                    fault_hook,
                    "after_tool_checkpoint",
                    {
                        "turn_id": turn_id,
                        "logical_call_id": call["logical_call_id"],
                        "tool_index": index,
                    },
                )
            checkpoint["round"] = int(
                checkpoint.get("round") or 0
            ) + 1
            checkpoint["tool_calls"] = []
            checkpoint["tool_index"] = 0
            checkpoint["phase"] = "model"
            _persist(context, checkpoint)
            continue

        if phase == "finalize":
            result = _finalize_turn(database, context, checkpoint)
            checkpoint["assistant_message_id"] = result.get(
                "assistant_message_id"
            )
            checkpoint["phase"] = "done"
            _persist(context, checkpoint)
            _event(
                context,
                turn_id,
                live_emit,
                {
                    "type": "message",
                    "message_id": result.get("assistant_message_id"),
                    "text": checkpoint.get("final_text") or "已完成。",
                },
            )
            _event(
                context,
                turn_id,
                live_emit,
                {
                    "type": "done",
                    "message_id": result.get("assistant_message_id"),
                    "usage": {
                        "prompt": result["prompt_tokens"],
                        "completion": result["completion_tokens"],
                    },
                    "canceled": False,
                    "failed": False,
                },
            )
            _fault(
                fault_hook,
                "after_turn_finalized",
                deepcopy(result),
            )
            return result

        raise RuntimeError(f"unknown Agent checkpoint phase: {phase}")


__all__ = [
    "AGENT_PLAN_KIND",
    "AGENT_TASK_TYPE",
    "CHECKPOINT_VERSION",
    "run_durable_agent_turn",
]
