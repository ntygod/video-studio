
import json
from typing import Any
from app.integrations.llm import LLMClient, LLMConfigurationError
from app.store import UnitOfWork

DIRECTOR_SYSTEM_PROMPT = "你是一个通用创作系统中的 AI 创作总监，不是只会写短视频旁白的编剧。\n用户可以创作任意内容、任意结构、任意数量的创作单元。不要擅自假设集数、短视频、科普或连续剧。\n你不能直接修改项目，需要修改时输出 proposal 由用户审核。只输出 JSON 对象。"

def _llm_provider(uow):
    for provider in uow.providers.list():
        if provider["capability_type"] == "llm" and provider["enabled"]:
            return uow.providers.get(provider["id"], include_secret=True)
    raise LLMConfigurationError("没有启用的 LLM provider profile")

def send_message(database, conversation_id, content):
    with UnitOfWork(database) as uow:
        conversation = uow.conversations.get(conversation_id)
        project = uow.projects.get(conversation["project_id"])
        user_message = uow.conversations.add_message(conversation_id, "user", content.strip())
        artifacts = uow.artifacts.list(project.id, conversation.get("unit_id"))
        artifact_context = [
            {"id": artifact["id"], "kind": artifact["kind"], "schema_id": artifact["schema_id"],
             "current_version_id": artifact.get("current_version_id"),
             "payload": (artifact.get("current_version") or {}).get("payload"),
             "status": (artifact.get("current_version") or {}).get("status")}
            for artifact in artifacts
        ]
        history = uow.conversations.list_messages(conversation_id)
        provider = _llm_provider(uow)
        project_json = project.model_dump(mode="json")
        unit_id = conversation.get("unit_id")
        project_id = project.id
        context = {"project": project_json, "selected_unit_id": unit_id, "artifacts": artifact_context}
        messages = [
            {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
            {"role": "system", "content": "当前项目上下文：" + json.dumps(context, ensure_ascii=False)},
        ]
        messages.extend({"role": item["role"], "content": item["content"]} for item in history if item["role"] in ("user", "assistant"))
    result = LLMClient(provider).chat_json(messages)
    proposal_ids = []
    proposals = []
    with UnitOfWork(database) as uow:
        for proposal_data in result.get("proposals") or []:
            artifact_id = proposal_data.get("artifact_id")
            base_version_id = None
            if artifact_id:
                artifact = uow.artifacts.get(artifact_id)
                base_version_id = artifact.get("current_version_id")
            elif proposal_data.get("artifact_kind") in ("brief", "project_bible"):
                match = next((artifact for artifact in uow.artifacts.list(project_id, unit_id=unit_id) if artifact["kind"] == proposal_data["artifact_kind"]), None)
                if match:
                    artifact_id = match["id"]
                    base_version_id = match.get("current_version_id")
            proposal = uow.proposals.create({
                "project_id": project_id,
                "unit_id": unit_id,
                "artifact_id": artifact_id,
                "artifact_kind": proposal_data.get("artifact_kind") or "custom",
                "base_version_id": base_version_id,
                "title": proposal_data.get("title") or "AI 修改提案",
                "rationale": proposal_data.get("rationale", ""),
                "operations": proposal_data.get("operations", []),
                "proposed_payload": proposal_data.get("proposed_payload"),
            })
            proposal_ids.append(proposal["id"])
            proposals.append(proposal)
        assistant_content = str(result.get("assistant_message") or "我已经整理了创作建议。")
        assistant_message = uow.conversations.add_message(conversation_id, "assistant", assistant_content, proposal_ids=proposal_ids)
    return {"user_message": user_message, "assistant_message": assistant_message, "proposals": proposals}

