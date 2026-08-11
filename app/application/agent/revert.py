"""Agent 回合副作用的安全撤销。

旧实现通过 ``ArtifactRow.revision > 1`` 判断稿件是否被修改，但新建 Artifact 在
创建首版时 revision 已经从 1 增加到 2，导致刚由 Agent 创建的草稿永远无法撤销。
这里按真实版本、状态和引用关系判断是否仍是“本回合原样产物”。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func, select

from app.store import UnitOfWork
from app.store.models import (
    ArtifactRow,
    ArtifactVersionRow,
    AssetRow,
    ConversationRow,
    CreativeUnitRow,
    JobRow,
    ProposalRow,
)
from app.store.repositories import ConflictError


def _skipped(entry: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**entry, "reason": reason}


def _has_rows(session, model, *conditions) -> bool:
    count = session.scalar(
        select(func.count()).select_from(model).where(*conditions)
    )
    return bool(count)


def _revert_artifact(uow: UnitOfWork, entry: dict[str, Any]) -> tuple[bool, str]:
    artifact = uow.session.get(ArtifactRow, entry["id"])
    if artifact is None:
        return True, "already_missing"

    versions = uow.session.scalars(
        select(ArtifactVersionRow)
        .where(ArtifactVersionRow.artifact_id == artifact.id)
        .order_by(ArtifactVersionRow.version)
    ).all()
    if len(versions) != 1:
        return False, "artifact_has_later_versions"

    version = versions[0]
    if (
        artifact.current_version_id != version.id
        or version.source != "ai"
        or version.status != "draft"
    ):
        return False, "artifact_not_pristine"

    if _has_rows(
        uow.session,
        ProposalRow,
        ProposalRow.artifact_id == artifact.id,
    ):
        return False, "artifact_has_proposals"

    uow.session.delete(artifact)
    uow.session.flush()
    return True, ""


def _revert_unit(uow: UnitOfWork, entry: dict[str, Any]) -> tuple[bool, str]:
    unit = uow.session.get(CreativeUnitRow, entry["id"])
    if unit is None:
        return True, "already_missing"
    if unit.updated_at > unit.created_at + 0.001:
        return False, "unit_was_modified"

    blockers = (
        (CreativeUnitRow, CreativeUnitRow.parent_id == unit.id, "unit_has_children"),
        (ArtifactRow, ArtifactRow.unit_id == unit.id, "unit_has_artifacts"),
        (AssetRow, AssetRow.unit_id == unit.id, "unit_has_assets"),
        (JobRow, JobRow.unit_id == unit.id, "unit_has_jobs"),
        (ConversationRow, ConversationRow.unit_id == unit.id, "unit_has_conversations"),
        (ProposalRow, ProposalRow.unit_id == unit.id, "unit_has_proposals"),
    )
    for model, condition, reason in blockers:
        if _has_rows(uow.session, model, condition):
            return False, reason

    uow.session.delete(unit)
    uow.session.flush()
    return True, ""


def _revert_asset(uow: UnitOfWork, entry: dict[str, Any]) -> tuple[bool, str]:
    asset = uow.session.get(AssetRow, entry["id"])
    if asset is None:
        return True, "already_missing"
    if _has_rows(
        uow.session,
        AssetRow,
        AssetRow.parent_asset_id == asset.id,
    ):
        return False, "asset_has_derivatives"

    uow.session.delete(asset)
    uow.session.flush()
    return True, ""


def _request_job_cancel(
    uow: UnitOfWork, entry: dict[str, Any]
) -> tuple[bool, str]:
    job = uow.session.get(JobRow, entry["id"])
    if job is None:
        return True, "already_missing"
    if job.status in ("queued", "running"):
        job.cancel_requested = True
        job.updated_at = time.time()
        uow.session.flush()
        return False, "job_cancel_requested"
    return False, "job_history_preserved"


def revert_agent_turn(database, turn_id: str) -> dict[str, Any]:
    """撤销一个已结束回合仍可安全逆转的直接副作用。

    任务历史不会删除；运行中的任务只请求取消。任何已被用户修改、批准、引用或
    继续派生的实体都会保留，并在 ``skipped`` 中给出机器可读原因。
    """

    with UnitOfWork(database) as uow:
        turn = uow.agent_turns.get(turn_id)
        if turn["status"] == "running":
            raise ConflictError("运行中的回合请先取消，再执行撤销")
        if turn["status"] == "reverted":
            return {"turn": turn, "reverted": [], "skipped": []}

        reverted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        handlers = {
            "artifact": _revert_artifact,
            "unit": _revert_unit,
            "asset": _revert_asset,
            "job": _request_job_cancel,
        }

        for raw_entry in reversed(turn.get("created_entities") or []):
            entry = {
                "type": str(raw_entry.get("type") or ""),
                "id": str(raw_entry.get("id") or ""),
            }
            handler = handlers.get(entry["type"])
            if not entry["id"] or handler is None:
                skipped.append(_skipped(entry, "unsupported_entity"))
                continue
            removed, reason = handler(uow, entry)
            if removed:
                reverted.append(entry)
            else:
                skipped.append(_skipped(entry, reason))

        uow.agent_turns.set_status(turn_id, "reverted")
        return {
            "turn": uow.agent_turns.get(turn_id),
            "reverted": reverted,
            "skipped": skipped,
        }
