from __future__ import annotations

import json
from typing import Any

from app.integrations.llm import LLMClient
from app.store import UnitOfWork


EDIT_PROMPT = """你是通用 AI 剪辑师。根据镜头计划与素材，输出 JSON 剪辑决策。
不要假设视频类型、时长或固定节奏。每条 decision 必须包含：
shot_id, asset_id, source_in, source_out, duration, speed, hold_after,
transition_in {kind, duration, reason}, audio {music_action, duck_db, sfx_asset_ids, reason},
reason, confidence。
只输出 JSON 对象。"""


def generate_edit_plan(database, project_id: str, unit_id: str | None) -> dict[str, Any]:
    with UnitOfWork(database) as uow:
        from app.application.providers import provider_for_capability

        provider = provider_for_capability(uow, "llm")
        artifacts = uow.artifacts.list(project_id, unit_id=unit_id)
        assets = uow.assets.list(project_id, unit_id=unit_id)
        shot_plan = next(
            (artifact["current_version"]["payload"] for artifact in artifacts if artifact["kind"] == "shot_plan" and artifact.get("current_version")),
            {},
        )
        context = {
            "shot_plan": shot_plan,
            "assets": [
                {"id": asset["id"], "kind": asset["kind"], "name": asset["name"], "uri": asset["uri"]}
                for asset in assets
            ],
        }
    response = LLMClient(provider).chat_json(
        [
            {"role": "system", "content": EDIT_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
    )
    with UnitOfWork(database) as uow:
        artifact = uow.artifacts.find_latest(project_id, unit_id, "edit_plan")
        if artifact:
            uow.artifacts.add_version(
                artifact["id"],
                response,
                source="ai_edit",
                note="重新生成 AI 剪辑计划",
            )
            artifact = uow.artifacts.get(artifact["id"])
        else:
            artifact = uow.artifacts.create(
                project_id=project_id,
                unit_id=unit_id,
                kind="edit_plan",
                name="AI 剪辑计划",
                schema_id="open/edit_plan@1",
                payload=response,
                source="ai_edit",
            )
        return artifact
