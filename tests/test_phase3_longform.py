"""Phase 3：分页瘦身、FTS5 检索、上下文压缩、项目列表字段。"""

import json
import threading
import time

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class CompactionFakeHandler(BaseHTTPRequestHandler):
    """顺序返回预设 JSON；Agent 回合与摘要 job 共用。"""

    responses: list[dict] = []
    count = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        index = CompactionFakeHandler.count
        CompactionFakeHandler.count += 1
        payload = CompactionFakeHandler.responses[min(index, len(CompactionFakeHandler.responses) - 1)]
        body = json.dumps({"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


@pytest.fixture()
def compaction_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CompactionFakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    CompactionFakeHandler.responses = []
    CompactionFakeHandler.count = 0
    yield server
    server.shutdown()
    thread.join(timeout=3)


def _add_llm_provider(client, base_url):
    response = client.post(
        "/api/provider-profiles",
        json={
            "name": "Phase3 LLM",
            "capability_type": "llm",
            "adapter": "unknown",
            "base_url": base_url,
            "api_key": "test",
            "enabled": True,
            "models": [{"name": "m", "model_id": "m", "capability_type": "llm"}],
        },
    )
    assert response.status_code == 201


def test_project_detail_is_slim_with_stats(client, project):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "一章", "unit_type": "chapter"}]},
    ).json()[0]
    client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"unit_id": unit["id"], "kind": "script", "name": "剧本", "payload": {"body": "x"}},
    )
    client.post(
        f"/api/projects/{project['id']}/assets",
        json={"kind": "image", "name": "图", "uri": f"{project['id']}/x.png", "mime_type": "image/png"},
    )
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert "units" not in detail
    assert "artifacts" not in detail
    assert "pending_proposals" not in detail
    assert detail["unit_count"] == 1
    assert detail["artifact_count"] == 3  # brief + bible + 新稿件
    assert detail["asset_count"] == 1
    assert detail["pending_proposal_count"] == 0
    assert detail["last_activity"] > 0


def test_project_list_has_aggregate_fields(client, project):
    asset = client.post(
        f"/api/projects/{project['id']}/assets",
        json={"kind": "image", "name": "封面", "uri": f"{project['id']}/cover.png", "mime_type": "image/png"},
    ).json()
    projects = client.get("/api/projects").json()
    entry = next(item for item in projects if item["id"] == project["id"])
    assert entry["cover_asset_id"] == asset["id"]
    assert entry["unit_count"] == 0
    assert entry["pending_proposal_count"] == 0
    assert entry["last_activity"] > 0


def test_units_pagination_with_depth(client, project):
    created = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "A", "unit_type": "volume"},
                {"title": "B", "unit_type": "volume"},
            ]
        },
    ).json()
    client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "A1", "unit_type": "chapter", "parent_id": created[0]["id"]},
                {"title": "A2", "unit_type": "chapter", "parent_id": created[0]["id"]},
                {"title": "B1", "unit_type": "chapter", "parent_id": created[1]["id"]},
            ]
        },
    ).json()

    # depth=1：只有根级，游标分页
    page1 = client.get(f"/api/projects/{project['id']}/units", params={"limit": 1}).json()
    assert [item["title"] for item in page1["items"]] == ["A"]
    assert page1["next_cursor"]
    page2 = client.get(
        f"/api/projects/{project['id']}/units", params={"limit": 1, "cursor": page1["next_cursor"]}
    ).json()
    assert [item["title"] for item in page2["items"]] == ["B"]
    assert page2["next_cursor"] is None

    # depth=2：先父后子全部展开
    all_items = client.get(f"/api/projects/{project['id']}/units", params={"depth": 2}).json()["items"]
    assert [item["title"] for item in all_items] == ["A", "B", "A1", "A2", "B1"]

    # 指定父级
    children = client.get(
        f"/api/projects/{project['id']}/units", params={"parent_id": created[0]["id"]}
    ).json()["items"]
    assert [item["title"] for item in children] == ["A1", "A2"]


def test_artifacts_pagination_and_slim_payload(client, project):
    for index in range(3):
        response = client.post(
            f"/api/projects/{project['id']}/artifacts",
            json={"kind": "script", "name": f"稿{index}", "payload": {"body": f"内容{index}"}},
        )
        assert response.status_code == 201
    page1 = client.get(
        f"/api/projects/{project['id']}/artifacts", params={"limit": 2, "kind": "script"}
    ).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    assert "payload" not in page1["items"][0]["current_version"]
    page2 = client.get(
        f"/api/projects/{project['id']}/artifacts",
        params={"limit": 2, "kind": "script", "cursor": page1["next_cursor"]},
    ).json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None


def test_assets_and_jobs_pagination(client, project):
    for index in range(3):
        client.post(
            f"/api/projects/{project['id']}/assets",
            json={"kind": "image", "name": f"图{index}", "uri": f"{project['id']}/{index}.png", "mime_type": "image/png"},
        )
    page1 = client.get(f"/api/projects/{project['id']}/assets", params={"limit": 2}).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    page2 = client.get(
        f"/api/projects/{project['id']}/assets", params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["items"]) == 1

    from app.store import UnitOfWork

    with UnitOfWork(client.app.state.database) as uow:
        for index in range(3):
            uow.jobs.create(
                {
                    "project_id": project["id"],
                    "job_type": "noop",
                    "payload": {"capability": "llm"},
                }
            )
    jobs_page = client.get("/api/jobs", params={"project_id": project["id"], "limit": 2}).json()
    assert len(jobs_page["items"]) == 2
    assert jobs_page["next_cursor"]
    assert all(item["status"] == "queued" for item in jobs_page["items"])


def test_fts_search_units_and_artifacts(client, project):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "赛博朋克侦探档案", "unit_type": "chapter", "summary": "雨夜追查霓虹灯下的线人"}]},
    ).json()[0]
    client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "unit_id": unit["id"],
            "kind": "script",
            "name": "第一场",
            "payload": {"scene": "霓虹灯招牌闪烁，侦探走进地下酒吧"},
        },
    )
    unit_hits = client.get(
        f"/api/projects/{project['id']}/search", params={"q": "赛博朋克", "type": "unit"}
    ).json()
    assert any(hit["id"] == unit["id"] for hit in unit_hits)
    artifact_hits = client.get(
        f"/api/projects/{project['id']}/search", params={"q": "霓虹灯", "type": "artifact"}
    ).json()
    assert len(artifact_hits) == 1
    assert artifact_hits[0]["type"] == "artifact"
    assert artifact_hits[0]["unit_id"] == unit["id"]


def test_continuity_summary_job_updates_unit(client, project, compaction_server):
    _add_llm_provider(client, f"http://127.0.0.1:{compaction_server.server_port}")
    CompactionFakeHandler.responses = [{"final": "单元摘要：主角在雨夜追查线人。"}]
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "第一章", "unit_type": "chapter"}]},
    ).json()[0]
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"unit_id": unit["id"], "kind": "script", "name": "剧本", "payload": {"body": "追查"}},
    ).json()
    version = artifact["current_version"]
    response = client.post(f"/api/artifact-versions/{version['id']}/approve")
    assert response.status_code == 200

    deadline = time.monotonic() + 20
    summary = None
    while time.monotonic() < deadline:
        jobs = client.get("/api/jobs", params={"project_id": project["id"]}).json()["items"]
        summary = next((job for job in jobs if job["job_type"] == "summary"), None)
        if summary and summary["status"] in ("succeeded", "failed", "canceled"):
            break
        time.sleep(0.2)
    assert summary is not None, "摘要 job 未派发"
    assert summary["status"] == "succeeded", summary
    updated = client.get(f"/api/projects/{project['id']}/units/{unit['id']}").json()
    assert "雨夜追查线人" in updated["continuity_summary"]


def test_conversation_compaction_marks_old_messages(client, project, compaction_server):
    _add_llm_provider(client, f"http://127.0.0.1:{compaction_server.server_port}")
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations", json={"title": "长对话", "unit_id": None}
    ).json()

    from app.store import UnitOfWork

    with UnitOfWork(client.app.state.database) as uow:
        for index in range(40):
            role = "user" if index % 2 == 0 else "assistant"
            uow.conversations.add_message(conversation["id"], role, f"第{index}条消息")

    CompactionFakeHandler.responses = [
        {"final": "回合回复"},
        {"final": "压缩后的对话摘要"},
    ]
    started = client.post(
        f"/api/conversations/{conversation['id']}/turns",
        json={"content": "继续", "context_refs": []},
    )
    assert started.status_code == 201

    deadline = time.monotonic() + 20
    summary_job = None
    while time.monotonic() < deadline:
        jobs = client.get("/api/jobs", params={"project_id": project["id"]}).json()["items"]
        summary_job = next(
            (job for job in jobs if job["job_type"] == "summary"), None
        )
        if summary_job and summary_job["status"] in ("succeeded", "failed", "canceled"):
            break
        time.sleep(0.2)
    assert summary_job is not None
    assert summary_job["status"] == "succeeded", summary_job

    conversation_data = client.get(f"/api/conversations/{conversation['id']}").json()
    roles = [message["role"] for message in conversation_data["messages"]]
    assert roles.count("compacted") == 20
    assert any(role == "system" and "[滚动摘要]" in message["content"] for role, message in zip(roles, conversation_data["messages"]))


def test_pinned_refs_inject_into_agent_context(client, project):
    from app.application.agent.context import build_initial_context
    from app.store import UnitOfWork

    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "钉住的章节", "unit_type": "chapter", "summary": "关键设定"}]},
    ).json()[0]
    detail = client.get(f"/api/projects/{project['id']}").json()
    response = client.patch(
        f"/api/projects/{project['id']}",
        json={
            "expected_revision": detail["revision"],
            "patch": {
                "settings": {
                    **detail["settings"],
                    "pinned_refs": [{"type": "unit", "id": unit["id"]}],
                }
            },
        },
    )
    assert response.status_code == 200
    with UnitOfWork(client.app.state.database) as uow:
        context_text, _ = build_initial_context(uow, project["id"], None, [])
    assert "钉住的章节" in context_text
    assert "关键设定" in context_text
