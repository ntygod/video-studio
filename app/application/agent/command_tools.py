"""CommandBus-backed implementations for mutating Agent tools.

The public tool specs remain in ``tools.py``. At package import time these
handlers replace the legacy direct-repository implementations so every Agent
side effect gets the same validation, idempotency and OperationLog as HTTP
writes.
"""

from __future__ import annotations

from typing import Any, Callable

from app.api.logging import current_request_id
from app.application.commands import (
    CommandBus,
    CommandContext,
    CreateArtifactChangeProposalCommand,
    CreateArtifactCommand,
    CreateJobCommand,
    CreateStructureProposalCommand,
    CreateUnitsCommand,
)

from .tools import TOOL_BY_NAME, ToolContext

CommandToolHandler = Callable[
    [ToolContext, dict[str, Any]],
    dict[str, Any],
]


def _running_step_id(
    ctx: ToolContext,
    tool_name: str,
) -> str:
    explicit = str(getattr(ctx, "step_id", "") or "")
    for step in reversed(
        ctx.uow.agent_turns.steps(ctx.turn_id)
    ):
        if explicit and step["id"] != explicit:
            continue
        if (
            step["kind"] == "tool"
            and step["tool_name"] == tool_name
            and step["status"] == "running"
        ):
            return step["id"]
    if explicit:
        raise RuntimeError(
            f"Agent tool step is not running: {explicit}"
        )
    raise RuntimeError(
        f"Agent tool step is missing: {tool_name}"
    )


def _execute(
    ctx: ToolContext,
    tool_name: str,
    command,
):
    step_id = _running_step_id(ctx, tool_name)
    return CommandBus(ctx.uow.database).execute(
        command,
        CommandContext(
            actor_type="agent",
            actor_id="creative-director",
            request_id=current_request_id(),
            turn_id=ctx.turn_id,
            idempotency_key=(
                f"agent:{ctx.turn_id}:{step_id}"
            ),
        ),
    )


def _id_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key) or []
    if not isinstance(value, list):
        raise ValueError(f"{key} 必须是数组")
    if len(value) > 500:
        raise ValueError(f"{key} 不能超过 500 项")
    return [
        normalized
        for item in value
        if (normalized := str(item or "").strip())
    ]


def _explicit_input_fields(
    args: dict[str, Any],
) -> dict[str, list[str]]:
    return {
        "input_version_ids": _id_list(
            args,
            "input_version_ids",
        ),
        "input_artifact_ids": _id_list(
            args,
            "input_artifact_ids",
        ),
        "input_asset_ids": _id_list(
            args,
            "input_asset_ids",
        ),
    }


def _write_artifact(
    ctx: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    payload = args.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(
            "write_artifact 的 payload 必须是 JSON 对象"
        )
    inputs = _explicit_input_fields(args)
    execution = _execute(
        ctx,
        "write_artifact",
        CreateArtifactCommand(
            project_id=ctx.project_id,
            unit_id=args.get("unit_id") or ctx.unit_id,
            kind=str(args.get("kind") or "generated"),
            name=str(args.get("name") or "AI 生成"),
            schema_id=str(
                args.get("schema_id") or "freeform"
            ),
            payload=payload,
            source="ai",
            input_context_turn_id=ctx.turn_id,
            input_version_ids=inputs["input_version_ids"],
            input_artifact_ids=inputs["input_artifact_ids"],
            input_asset_ids=inputs["input_asset_ids"],
            dependency_type="agent_generated_from",
            asset_dependency_type=(
                "agent_generated_with_asset"
            ),
            dependency_metadata={
                "tool_name": "write_artifact",
                "turn_id": ctx.turn_id,
            },
            provenance={
                "prompt_version": "agent-write-artifact@1",
                "task_attempt_id": f"agent-turn:{ctx.turn_id}",
            },
        ),
    )
    artifact = execution.result
    version = artifact.get("current_version") or {}
    entity = {"type": "artifact", "id": artifact["id"]}
    return {
        "artifact_id": artifact["id"],
        "version": version.get("version", 1),
        "version_id": version.get("id"),
        "operation_id": execution.operation["id"],
        "entities": [entity],
    }


def _create_units(
    ctx: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    definitions = args.get("units")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("units 必须是非空数组")
    execution = _execute(
        ctx,
        "create_units",
        CreateUnitsCommand(
            project_id=ctx.project_id,
            definitions=definitions,
        ),
    )
    units = execution.result
    entities = [
        {"type": "unit", "id": unit["id"]}
        for unit in units
    ]
    return {
        "units": [
            {"id": unit["id"], "title": unit["title"]}
            for unit in units
        ],
        "operation_id": execution.operation["id"],
        "entities": entities,
    }


def _generate_media(
    ctx: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    kind = str(args.get("kind") or "")
    if kind not in ("image", "video", "voice"):
        raise ValueError("kind 必须是 image/video/voice")
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是 JSON 对象")
    inputs = _explicit_input_fields(args)

    if kind == "voice":
        payload = {
            "capability": "tts",
            "text": prompt,
            "voice": params.get(
                "voice",
                "zh-CN-XiaoxiaoNeural",
            ),
            "rate": params.get("rate", "+0%"),
            "name": params.get("name", "配音"),
        }
    else:
        payload = {
            "capability": kind,
            "prompt": prompt,
            "parameters": params,
            "name": params.get("name", f"AI {kind}"),
        }
    payload.update(inputs)
    payload["_request_id"] = current_request_id()

    execution = _execute(
        ctx,
        "generate_media",
        CreateJobCommand(
            project_id=ctx.project_id,
            unit_id=args.get("unit_id") or ctx.unit_id,
            job_type="media",
            payload=payload,
            turn_id=ctx.turn_id,
        ),
    )
    job = execution.result
    # Workers poll the durable queue, so this notification is only a latency
    # optimization. A replay of an already terminal job must never revive it.
    if job["status"] == "queued":
        ctx.job_engine.submit(job["id"])
    entity = {"type": "job", "id": job["id"]}
    return {
        "job_id": job["id"],
        "operation_id": execution.operation["id"],
        "entities": [entity],
    }


def _propose_change(
    ctx: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    artifact_id = str(args.get("artifact_id") or "")
    operations = args.get("operations")
    if not artifact_id:
        raise ValueError("artifact_id 必填")
    if not isinstance(operations, list):
        raise ValueError("operations 必须是数组")
    execution = _execute(
        ctx,
        "propose_change",
        CreateArtifactChangeProposalCommand(
            project_id=ctx.project_id,
            unit_id=ctx.unit_id,
            artifact_id=artifact_id,
            operations=operations,
            title=str(
                args.get("title") or "AI 修改提案"
            ),
            rationale=str(args.get("rationale") or ""),
        ),
    )
    proposal = execution.result
    return {
        "proposal_id": proposal["id"],
        "operation_id": execution.operation["id"],
    }


def _propose_restructure(
    ctx: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    changes = args.get("changes")
    if not isinstance(changes, list):
        raise ValueError("changes 必须是数组")
    execution = _execute(
        ctx,
        "propose_restructure",
        CreateStructureProposalCommand(
            project_id=ctx.project_id,
            unit_id=ctx.unit_id,
            changes=changes,
            title=str(
                args.get("title") or "AI 结构提案"
            ),
            rationale=str(args.get("rationale") or ""),
        ),
    )
    proposal = execution.result
    return {
        "proposal_id": proposal["id"],
        "operation_id": execution.operation["id"],
    }


HANDLERS: dict[str, CommandToolHandler] = {
    "write_artifact": _write_artifact,
    "create_units": _create_units,
    "generate_media": _generate_media,
    "propose_change": _propose_change,
    "propose_restructure": _propose_restructure,
}


def install_command_tool_handlers() -> None:
    for name, handler in HANDLERS.items():
        tool = TOOL_BY_NAME.get(name)
        if tool is None:
            raise RuntimeError(
                f"Agent command tool is not registered: {name}"
            )
        tool.handler = handler
        tool.mutates = True


__all__ = [
    "HANDLERS",
    "install_command_tool_handlers",
]
