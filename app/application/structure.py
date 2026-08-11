"""结构提案的应用与预览。

AI 通过 propose_restructure 提出单元的移动/重命名/重排/删除，用户采纳后由这里
真正落到 creative_units 上。这些变更不产生 artifact——它们改的是项目结构本身。
"""

from __future__ import annotations

from typing import Any

from app.store.repositories import ConflictError, NotFoundError

#: 支持的结构变更动作。
ACTIONS = ("move", "rename", "reorder", "delete")


def _require_unit(uow, project_id: str, unit_id: str):
    if not unit_id:
        raise ValueError("结构变更缺少 unit_id")
    unit = uow.units.get(unit_id)
    if unit.project_id != project_id:
        raise NotFoundError(unit_id)
    return unit


def _descendant_ids(uow, project_id: str, unit_id: str) -> set[str]:
    """收集某个单元的全部后代 id，用于阻止把父级移进自己的子树。

    一次取全量单元在内存里建父子索引；按层查会随树深退化成多次往返。
    """
    children_by_parent: dict[str, list[str]] = {}
    for unit in uow.units.list(project_id):
        if unit.parent_id:
            children_by_parent.setdefault(unit.parent_id, []).append(unit.id)

    result: set[str] = set()
    frontier = [unit_id]
    while frontier:
        for child_id in children_by_parent.get(frontier.pop(), []):
            if child_id in result:
                continue
            result.add(child_id)
            frontier.append(child_id)
    return result


def describe_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把结构变更渲染成可读摘要，供提案预览展示。"""
    described: list[dict[str, Any]] = []
    for index, change in enumerate(changes):
        action = str(change.get("action") or "")
        unit_id = str(change.get("unit_id") or "")
        if action == "move":
            parent = change.get("parent_id")
            target = f"移动到 {parent}" if parent else "移动到项目根级"
        elif action == "rename":
            target = f"重命名为「{change.get('title', '')}」"
        elif action == "reorder":
            target = f"排序改为 {change.get('order_index')}"
        elif action == "delete":
            target = "删除（含全部子单元）"
        else:
            target = f"未知动作 {action}"
        described.append({"index": index, "action": action, "unit_id": unit_id, "summary": target})
    return described


def preview_structure_changes(uow, project_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """预览：带上单元当前标题，并标出无法应用的条目。"""
    described = describe_changes(changes)
    for item in described:
        try:
            unit = _require_unit(uow, project_id, item["unit_id"])
            item["title"] = unit.title
            item["applicable"] = item["action"] in ACTIONS
        except (NotFoundError, ValueError) as exc:
            item["title"] = ""
            item["applicable"] = False
            item["reason"] = str(exc)
    return {"changes": described}


def apply_structure_changes(
    uow, project_id: str, changes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按顺序应用结构变更，返回每条的执行结果。

    任何一条非法（单元不存在、跨项目、成环）都会抛错，整个事务回滚——
    结构变更是相互依赖的，部分应用会留下比拒绝更糟的中间状态。
    """
    applied: list[dict[str, Any]] = []
    for change in changes:
        action = str(change.get("action") or "")
        unit_id = str(change.get("unit_id") or "")
        unit = _require_unit(uow, project_id, unit_id)

        if action == "move":
            parent_id = change.get("parent_id") or None
            if parent_id:
                if parent_id == unit_id:
                    raise ConflictError(f"单元不能成为自己的父级：{unit_id}")
                _require_unit(uow, project_id, parent_id)
                if parent_id in _descendant_ids(uow, project_id, unit_id):
                    raise ConflictError(f"不能把单元移动到自己的子树内：{unit_id}")
            data = unit.model_copy(update={"parent_id": parent_id})
            if change.get("order_index") is not None:
                data = data.model_copy(update={"order_index": float(change["order_index"])})
            uow.units.update(data)

        elif action == "rename":
            title = str(change.get("title") or "").strip()
            if not title:
                raise ValueError(f"重命名缺少 title：{unit_id}")
            uow.units.update(unit.model_copy(update={"title": title}))

        elif action == "reorder":
            if change.get("order_index") is None:
                raise ValueError(f"重排缺少 order_index：{unit_id}")
            uow.units.update(
                unit.model_copy(update={"order_index": float(change["order_index"])})
            )

        elif action == "delete":
            uow.units.delete(unit_id)

        else:
            raise ValueError(f"不支持的结构动作：{action}（可选 {'/'.join(ACTIONS)}）")

        applied.append({"action": action, "unit_id": unit_id, "title": unit.title})
    return applied
