from __future__ import annotations

from typing import Any

from app.store import UnitOfWork


def _estimate_tokens(text: str) -> int:
    # 中英文混排的粗略估算：约 1.6 字符/token
    return max(1, int(len(text) / 1.6))


def _artifact_summary(uow: UnitOfWork, artifact_id: str) -> str:
    artifact = uow.artifacts.get(artifact_id)
    version = artifact.get("current_version") or {}
    payload = version.get("payload") or {}
    keys = ", ".join(list(payload.keys())[:12])
    return f"{artifact['kind']}「{artifact['name']}」v{version.get('version', 1)}（顶层键：{keys}）"


def build_initial_context(
    uow: UnitOfWork,
    project_id: str,
    unit_id: str | None,
    context_refs: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """只组装：项目一句话摘要 + 当前单元摘要 + 显式 context_refs + 圣经片段。

    绝不转储全部 artifacts。返回 (上下文文本, 预估 token 数)。
    """
    project = uow.projects.get(project_id)
    parts: list[str] = []
    brief = project.brief
    parts.append(f"项目：{project.title}（类型 {project.project_type or 'freeform'}）")
    if brief.concept:
        parts.append(f"构思：{brief.concept}")
    if brief.objective:
        parts.append(f"目标：{brief.objective}")

    if unit_id:
        try:
            unit = uow.units.get(unit_id)
            parts.append(f"当前单元：{unit.title}（{unit.unit_type}）")
            if unit.summary:
                parts.append(f"单元摘要：{unit.summary}")
            if unit.continuity_summary:
                parts.append(f"连贯性摘要：{unit.continuity_summary}")
        except Exception:
            parts.append(f"当前单元：{unit_id}（不可读）")

    for ref in (project.settings.pinned_refs or []) + (context_refs or []):
        ref_type = ref.get("type")
        ref_id = ref.get("id")
        try:
            if ref_type == "unit":
                unit = uow.units.get(ref_id)
                parts.append(f"引用单元：{unit.title}（{unit.unit_type}）{unit.summary or ''}")
            elif ref_type == "artifact":
                parts.append(f"引用稿件：{_artifact_summary(uow, ref_id)}")
            elif ref_type == "bible":
                section = str(ref.get("section") or "all")
                bible = project.bible.model_dump(mode="json")
                if section in bible:
                    parts.append(f"圣经·{section}：{bible[section]}")
                else:
                    parts.append(f"圣经·all：{bible}")
        except Exception:
            parts.append(f"引用实体不可读：{ref_type}:{ref_id}")

    text = "\n".join(parts)
    return text, _estimate_tokens(text)
