from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from app.application.projects import create_units as _create_units_service
from app.api.logging import current_request_id
from app.integrations.llm import ToolSpec
from app.store import UnitOfWork


@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    mutates: bool = False


@dataclass
class ToolContext:
    uow: UnitOfWork
    project_id: str
    unit_id: str | None
    turn_id: str
    settings: Any
    job_engine: Any

    def record(self, entity_type: str, entity_id: str) -> None:
        self.uow.agent_turns.record_entity(self.turn_id, entity_type, entity_id)


def _list_units(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    parent_id = args.get("parent_id")
    depth = int(args.get("depth") or 1)
    rows = ctx.uow.units.list(ctx.project_id, parent_id=parent_id)
    # 两次聚合查询换掉「每个单元再查一次子级 + 一次稿件」的 N+1。
    # 这是 Agent 在长篇项目里调用最频繁的工具，逐条查会放大成上百次往返。
    child_counts = ctx.uow.units.child_counts(ctx.project_id)
    units_with_artifacts = ctx.uow.artifacts.unit_ids_with_artifacts(ctx.project_id)
    children_by_parent: dict[str, list[Any]] = {}
    if depth > 1:
        for unit in ctx.uow.units.list(ctx.project_id):
            if unit.parent_id:
                children_by_parent.setdefault(unit.parent_id, []).append(unit)

    result = []
    for unit in rows:
        item = {
            "id": unit.id,
            "title": unit.title,
            "unit_type": unit.unit_type,
            "stage": unit.stage,
            "has_artifacts": unit.id in units_with_artifacts,
            "child_count": child_counts.get(unit.id, 0),
        }
        if depth > 1:
            children = children_by_parent.get(unit.id) or []
            if children:
                item["children"] = [
                    {"id": child.id, "title": child.title, "unit_type": child.unit_type}
                    for child in children
                ]
        result.append(item)
    return {"units": result}


def _read_unit(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    unit_id = str(args["unit_id"])
    unit = ctx.uow.units.get(unit_id)
    artifacts = ctx.uow.artifacts.list(
        ctx.project_id, unit_id=unit_id, include_payload=False
    )
    assets = ctx.uow.assets.list(ctx.project_id, unit_id=unit_id)
    return {
        "unit": {
            "id": unit.id,
            "title": unit.title,
            "unit_type": unit.unit_type,
            "stage": unit.stage,
            "summary": unit.summary,
            "continuity_summary": unit.continuity_summary,
            "parent_id": unit.parent_id,
        },
        "artifacts": [
            {
                "id": artifact["id"],
                "kind": artifact["kind"],
                "name": artifact["name"],
                "version": (artifact.get("current_version") or {}).get("version", 1),
            }
            for artifact in artifacts
        ],
        "asset_count": len(assets),
    }


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            summary[key] = {"type": "object", "keys": list(value.keys()), "length": len(value)}
        elif isinstance(value, list):
            summary[key] = {"type": "array", "count": len(value)}
        elif value is None:
            summary[key] = {"type": "null"}
        else:
            summary[key] = {"type": type(value).__name__, "length": len(str(value))}
    return summary


def _read_artifact(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(args["artifact_id"])
    artifact = ctx.uow.artifacts.get(artifact_id)
    version = artifact.get("current_version") or {}
    payload = version.get("payload") or {}
    path = args.get("path")
    if not path:
        return {
            "artifact_id": artifact_id,
            "kind": artifact["kind"],
            "name": artifact["name"],
            "version": version.get("version", 1),
            "status": version.get("status", "draft"),
            "summary": _payload_summary(payload),
            "hint": "用 path 参数读取具体子树",
        }
    cursor: Any = payload
    for token in str(path).split("."):
        if isinstance(cursor, list):
            cursor = cursor[int(token)]
        elif isinstance(cursor, dict):
            cursor = cursor.get(token)
        else:
            raise ValueError(f"path 不存在：{path}")
    return {"artifact_id": artifact_id, "path": path, "value": cursor}


def _search(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"results": []}
    kind = str(args.get("kind") or "all")
    limit = max(1, min(int(args.get("limit") or 10), 50))
    results = ctx.uow.search.search(
        ctx.project_id, query, kind=kind, limit=limit
    )
    return {"results": results}
def _read_bible(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    section = str(args.get("section") or "all")
    project = ctx.uow.projects.get(ctx.project_id)
    bible = project.bible.model_dump(mode="json")
    if section == "all":
        return {"bible": bible}
    if section in bible:
        return {"bible": {section: bible[section]}}
    raise ValueError(f"未知 bible 片段：{section}（可选 characters/world/style/all）")


def _list_assets(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    unit_id = args.get("unit_id")
    kind = args.get("kind")
    assets = ctx.uow.assets.list(ctx.project_id, unit_id=unit_id)
    result = []
    for asset in assets:
        if kind and asset["kind"] != kind:
            continue
        metadata = asset.get("metadata") or {}
        result.append(
            {
                "id": asset["id"],
                "kind": asset["kind"],
                "name": asset["name"],
                "mime_type": asset["mime_type"],
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "duration": metadata.get("duration"),
            }
        )
    return {"assets": result}


def _write_artifact(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    payload = args.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("write_artifact 的 payload 必须是 JSON 对象")
    unit_id = args.get("unit_id") or ctx.unit_id
    artifact = ctx.uow.artifacts.create(
        project_id=ctx.project_id,
        unit_id=unit_id,
        kind=str(args.get("kind") or "generated"),
        name=str(args.get("name") or "AI 生成"),
        schema_id=str(args.get("schema_id") or "freeform"),
        payload=payload,
        source="ai",
    )
    entity = {"type": "artifact", "id": artifact["id"]}
    ctx.record(entity["type"], entity["id"])
    return {
        "artifact_id": artifact["id"],
        "version": (artifact.get("current_version") or {}).get("version", 1),
        "entities": [entity],
    }


def _create_units(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    definitions = args.get("units")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("units 必须是非空数组")
    units = _create_units_service(ctx.uow, ctx.project_id, definitions)
    entities = [{"type": "unit", "id": unit.id} for unit in units]
    for entity in entities:
        ctx.record(entity["type"], entity["id"])
    return {
        "units": [{"id": unit.id, "title": unit.title} for unit in units],
        "entities": entities,
    }


def _generate_media(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "")
    if kind not in ("image", "video", "voice"):
        raise ValueError("kind 必须是 image/video/voice")
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")
    unit_id = args.get("unit_id") or ctx.unit_id
    params = args.get("params") or {}
    if kind == "voice":
        payload = {
            "capability": "tts",
            "text": prompt,
            "voice": params.get("voice", "zh-CN-XiaoxiaoNeural"),
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
    payload["_request_id"] = current_request_id()
    job = ctx.uow.jobs.create(
        {
            "project_id": ctx.project_id,
            "unit_id": unit_id,
            "job_type": "media",
            "payload": payload,
        }
    )
    ctx.job_engine.submit(job["id"])
    entity = {"type": "job", "id": job["id"]}
    ctx.record(entity["type"], entity["id"])
    return {"job_id": job["id"], "entities": [entity]}


def _propose_change(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(args.get("artifact_id") or "")
    operations = args.get("operations")
    if not artifact_id or not isinstance(operations, list) or not operations:
        raise ValueError("artifact_id 与 operations 必填")
    artifact = ctx.uow.artifacts.get(artifact_id)
    proposal = ctx.uow.proposals.create(
        {
            "project_id": ctx.project_id,
            "unit_id": ctx.unit_id,
            "artifact_id": artifact_id,
            "artifact_kind": artifact["kind"],
            "base_version_id": artifact.get("current_version_id"),
            "title": str(args.get("title") or "AI 修改提案"),
            "rationale": str(args.get("rationale") or ""),
            "operations": operations,
        }
    )
    return {"proposal_id": proposal["id"]}


def _propose_restructure(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from app.application.structure import ACTIONS

    changes = args.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("changes 必须是非空数组")
    # 在建提案时就校验，让模型能在同一回合内改正，而不是等用户点采纳才报错。
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ValueError(f"changes[{index}] 必须是对象")
        action = str(change.get("action") or "")
        if action not in ACTIONS:
            raise ValueError(
                f"changes[{index}].action 非法：{action or '缺失'}（可选 {'/'.join(ACTIONS)}）"
            )
        if not change.get("unit_id"):
            raise ValueError(f"changes[{index}] 缺少 unit_id")
        if action == "rename" and not str(change.get("title") or "").strip():
            raise ValueError(f"changes[{index}] 是 rename，必须给 title")
        if action == "reorder" and change.get("order_index") is None:
            raise ValueError(f"changes[{index}] 是 reorder，必须给 order_index")
    proposal = ctx.uow.proposals.create(
        {
            "project_id": ctx.project_id,
            "unit_id": ctx.unit_id,
            "artifact_id": None,
            "artifact_kind": "structure",
            "base_version_id": None,
            "title": str(args.get("title") or "AI 结构提案"),
            "rationale": str(args.get("rationale") or ""),
            "operations": changes,
        }
    )
    return {"proposal_id": proposal["id"]}
def _spec(name, description, properties, required):
    return ToolSpec(name=name, description=description, parameters={"type": "object", "properties": properties, "required": required})


TOOLS: list[Tool] = [
    Tool(
        spec=_spec(
            "list_units",
            "列出创作单元（可按父级与深度）",
            {
                "parent_id": {"type": "string", "description": "父单元 id，省略表示项目根"},
                "depth": {"type": "integer", "description": "子级深度，默认 1"},
            },
            [],
        ),
        handler=_list_units,
    ),
    Tool(
        spec=_spec(
            "read_unit",
            "读取一个单元的摘要、稿件清单与素材数量",
            {"unit_id": {"type": "string"}},
            ["unit_id"],
        ),
        handler=_read_unit,
    ),
    Tool(
        spec=_spec(
            "read_artifact",
            "读取稿件：不给 path 只返回摘要，给 path 返回该子树全文",
            {
                "artifact_id": {"type": "string"},
                "path": {"type": "string", "description": "点分路径，如 第7章.对白"},
            },
            ["artifact_id"],
        ),
        handler=_read_artifact,
    ),
    Tool(
        spec=_spec(
            "search",
            "搜索单元与稿件",
            {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["unit", "artifact"]},
                "limit": {"type": "integer"},
            },
            ["query"],
        ),
        handler=_search,
    ),
    Tool(
        spec=_spec(
            "read_bible",
            "读取项目圣经片段（characters/world/style/all）",
            {"section": {"type": "string", "enum": ["characters", "world", "style", "all"]}},
            ["section"],
        ),
        handler=_read_bible,
    ),
    Tool(
        spec=_spec(
            "list_assets",
            "列出素材元信息（不含 uri 与二进制）",
            {
                "unit_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["image", "video", "voice", "reference", "render"]},
            },
            [],
        ),
        handler=_list_assets,
    ),
    Tool(
        spec=_spec(
            "write_artifact",
            "追加新建一份稿件（source=ai，首版 draft）",
            {
                "unit_id": {"type": "string"},
                "kind": {"type": "string"},
                "name": {"type": "string"},
                "schema_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            ["kind", "name", "payload"],
        ),
        handler=_write_artifact,
        mutates=True,
    ),
    Tool(
        spec=_spec(
            "create_units",
            "批量新建创作单元（追加）",
            {
                "units": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "unit_type": {"type": "string"},
                            "parent_id": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                    },
                }
            },
            ["units"],
        ),
        handler=_create_units,
        mutates=True,
    ),
    Tool(
        spec=_spec(
            "generate_media",
            "派发图片/视频/配音生成任务（追加）",
            {
                "kind": {"type": "string", "enum": ["image", "video", "voice"]},
                "prompt": {"type": "string"},
                "unit_id": {"type": "string"},
                "params": {"type": "object"},
            },
            ["kind", "prompt"],
        ),
        handler=_generate_media,
        mutates=True,
    ),
    Tool(
        spec=_spec(
            "propose_change",
            "对已有稿件提出逐条采纳的修改提案",
            {
                "artifact_id": {"type": "string"},
                "operations": {"type": "array", "items": {"type": "object"}},
                "title": {"type": "string"},
                "rationale": {"type": "string"},
            },
            ["artifact_id", "operations", "title"],
        ),
        handler=_propose_change,
    ),
    Tool(
        spec=_spec(
            "propose_restructure",
            "提出结构重构提案：移动/重命名/重排/删除创作单元，用户采纳后才生效",
            {
                "changes": {
                    "type": "array",
                    "description": "每条一个动作对象",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["move", "rename", "reorder", "delete"],
                            },
                            "unit_id": {"type": "string", "description": "被操作的单元 id"},
                            "parent_id": {
                                "type": "string",
                                "description": "move：新父级 id，省略或 null 表示移到项目根级",
                            },
                            "title": {"type": "string", "description": "rename：新标题"},
                            "order_index": {
                                "type": "number",
                                "description": "move/reorder：同级排序位置",
                            },
                        },
                        "required": ["action", "unit_id"],
                    },
                },
                "title": {"type": "string"},
                "rationale": {"type": "string"},
            },
            ["changes", "title"],
        ),
        handler=_propose_restructure,
    ),
]

TOOL_BY_NAME = {tool.spec.name: tool for tool in TOOLS}
