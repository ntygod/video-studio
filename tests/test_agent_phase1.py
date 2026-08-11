import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.application.artifacts import deep_merge
from app.store import UnitOfWork


class AgentFakeHandler(BaseHTTPRequestHandler):
    responses = []
    request_count = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        index = AgentFakeHandler.request_count
        AgentFakeHandler.request_count += 1
        payload = AgentFakeHandler.responses[min(index, len(AgentFakeHandler.responses) - 1)]
        body = json.dumps({"choices": [{"message": {"content": payload}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


@pytest.fixture()
def agent_fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentFakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    AgentFakeHandler.responses = []
    AgentFakeHandler.request_count = 0
    yield server
    server.shutdown()
    thread.join(timeout=3)


def _add_llm_provider(client, base_url):
    response = client.post(
        "/api/provider-profiles",
        json={
            "name": "测试 LLM",
            "capability_type": "llm",
            "adapter": "unknown",
            "base_url": base_url,
            "api_key": "test",
            "enabled": True,
            "models": [
                {"name": "fake", "model_id": "fake-model", "capability_type": "llm"}
            ],
        },
    )
    assert response.status_code == 201


def test_deep_merge_keeps_untouched_fields():
    base = {
        "title": "项目",
        "concept": "旧概念",
        "objective": "目标",
        "format_id": "freeform",
        "tone": ["悬疑"],
    }
    merged = deep_merge(base, {"concept": "新概念"})
    assert merged["concept"] == "新概念"
    assert merged["title"] == "项目"
    assert merged["objective"] == "目标"
    assert merged["format_id"] == "freeform"
    assert merged["tone"] == ["悬疑"]
def test_brief_proposal_accept_keeps_other_fields(client, project):
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()["items"]
    brief = next(item for item in artifacts if item["kind"] == "brief")
    detail = client.get(f"/api/projects/{project['id']}").json()
    with UnitOfWork(client.app.state.database) as uow:
        proposal = uow.proposals.create(
            {
                "project_id": project["id"],
                "unit_id": None,
                "artifact_id": brief["id"],
                "artifact_kind": "brief",
                "base_version_id": brief["current_version"]["id"],
                "title": "只改概念",
                "operations": [],
                "proposed_payload": {"concept": "只改概念的新版本"},
            }
        )
    preview = client.get(f"/api/proposals/{proposal['id']}/preview").json()
    assert preview["after"]["concept"] == "只改概念的新版本"
    assert preview["after"]["title"] == detail["brief"]["title"]
    response = client.post(f"/api/proposals/{proposal['id']}/accept", json={})
    assert response.status_code == 200
    updated = client.get(f"/api/artifacts/{brief['id']}").json()
    payload = updated["current_version"]["payload"]
    assert payload["concept"] == "只改概念的新版本"
    assert payload["objective"] == detail["brief"]["objective"]
    assert payload["format_id"] == detail["brief"]["format_id"]


def test_proposal_partial_accept_only_applies_selected_ops(client, project):
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()["items"]
    brief = next(item for item in artifacts if item["kind"] == "brief")
    detail = client.get(f"/api/projects/{project['id']}").json()
    operations = [
        {"op": "replace", "path": "/concept", "value": "改动一"},
        {"op": "replace", "path": "/objective", "value": "改动二"},
    ]
    with UnitOfWork(client.app.state.database) as uow:
        proposal = uow.proposals.create(
            {
                "project_id": project["id"],
                "unit_id": None,
                "artifact_id": brief["id"],
                "artifact_kind": "brief",
                "base_version_id": brief["current_version"]["id"],
                "title": "两条修改",
                "operations": operations,
            }
        )
    response = client.post(
        f"/api/proposals/{proposal['id']}/accept", json={"op_indices": [1]}
    )
    assert response.status_code == 200
    updated = client.get(f"/api/artifacts/{brief['id']}").json()
    payload = updated["current_version"]["payload"]
    assert payload["objective"] == "改动二"
    assert payload["concept"] == detail["brief"]["concept"]
def _wait_turn(client, turn_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = client.get(f"/api/turns/{turn_id}").json()
        if turn["status"] in ("succeeded", "failed", "canceled", "reverted"):
            return turn
        time.sleep(0.2)
    raise AssertionError(f"turn 未在 {timeout}s 内结束：{turn}")


def test_agent_turn_creates_units_and_can_revert(client, project, agent_fake_server):
    AgentFakeHandler.responses = [
        json.dumps(
            {
                "tool": "create_units",
                "args": {
                    "units": [
                        {"title": "第一章", "unit_type": "chapter"},
                        {"title": "第二章", "unit_type": "chapter"},
                    ]
                },
            },
            ensure_ascii=False,
        ),
        json.dumps({"final": "已创建两个单元。"}, ensure_ascii=False),
    ]
    _add_llm_provider(client, f"http://127.0.0.1:{agent_fake_server.server_port}")
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "对话", "unit_id": None},
    ).json()
    started = client.post(
        f"/api/conversations/{conversation['id']}/turns",
        json={"content": "帮我建两个单元", "context_refs": []},
    )
    assert started.status_code == 201
    turn_id = started.json()["turn_id"]
    turn = _wait_turn(client, turn_id)
    assert turn["status"] == "succeeded"
    kinds = [step["kind"] for step in turn["steps"]]
    assert "tool" in kinds
    assert any(step["tool_name"] == "create_units" for step in turn["steps"] if step["kind"] == "tool")
    assert len(turn["created_entities"]) == 2
    assert turn["assistant_message_id"]
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["unit_count"] >= 2
    units_page = client.get(f"/api/projects/{project['id']}/units").json()["items"]
    assert len(units_page) >= 2
    reverted = client.post(f"/api/turns/{turn_id}/revert").json()
    assert len(reverted["reverted"]) == 2
    detail_after = client.get(f"/api/projects/{project['id']}").json()
    assert detail_after["unit_count"] == 0


def test_agent_turn_failure_records_error_step(client, project, agent_fake_server):
    AgentFakeHandler.responses = [
        json.dumps({"tool": "read_unit", "args": {"unit_id": "missing"}}, ensure_ascii=False),
        json.dumps({"final": "完成"}, ensure_ascii=False),
    ]
    _add_llm_provider(client, f"http://127.0.0.1:{agent_fake_server.server_port}")
    conversation = client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "对话2", "unit_id": None},
    ).json()
    started = client.post(
        f"/api/conversations/{conversation['id']}/turns",
        json={"content": "读一个不存在的单元", "context_refs": []},
    )
    turn_id = started.json()["turn_id"]
    turn = _wait_turn(client, turn_id)
    # 工具失败是可恢复的：回合仍应正常结束，且步骤标记 failed
    failed_step = next(step for step in turn["steps"] if step["kind"] == "tool")
    assert failed_step["status"] == "failed"
    assert failed_step["error"]


def _make_structure_proposal(app, project_id, operations, title="整理结构"):
    from app.store import UnitOfWork

    with UnitOfWork(app.state.database) as uow:
        return uow.proposals.create(
            {
                "project_id": project_id,
                "unit_id": None,
                "artifact_id": None,
                "artifact_kind": "structure",
                "base_version_id": None,
                "title": title,
                "rationale": "测试用结构变更",
                "operations": operations,
            }
        )


def _units_of(client, project_id):
    return client.get(f"/api/projects/{project_id}/units", params={"depth": 5}).json()["items"]


def test_structure_proposal_actually_changes_units(app, client, project):
    """结构提案必须真的动单元树。

    之前 accept_proposal 遇到 artifact_id 为空就新建一份 kind=structure 的 artifact，
    单元一个都不动——用户点了采纳什么也没发生，只多出一份垃圾稿件。
    """
    created = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "卷一", "unit_type": "volume"},
                {"title": "第一章", "unit_type": "chapter"},
                {"title": "废弃章", "unit_type": "chapter"},
            ]
        },
    ).json()
    volume, chapter, dropped = created

    proposal = _make_structure_proposal(
        app,
        project["id"],
        [
            {"action": "move", "unit_id": chapter["id"], "parent_id": volume["id"], "order_index": 0},
            {"action": "rename", "unit_id": volume["id"], "title": "第一卷"},
            {"action": "delete", "unit_id": dropped["id"]},
        ],
    )

    preview = client.get(f"/api/proposals/{proposal['id']}/preview").json()
    assert len(preview["changes"]) == 3
    assert all(item["applicable"] for item in preview["changes"])
    assert preview["field_diffs"] == []

    response = client.post(f"/api/proposals/{proposal['id']}/accept", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact_id"] is None
    assert body["version"] is None
    assert [item["action"] for item in body["applied"]] == ["move", "rename", "delete"]

    units = {unit["id"]: unit for unit in _units_of(client, project["id"])}
    assert dropped["id"] not in units
    assert units[chapter["id"]]["parent_id"] == volume["id"]
    assert units[volume["id"]]["title"] == "第一卷"

    # 不能留下 kind=structure 的垃圾稿件
    artifacts = client.get(
        f"/api/projects/{project['id']}/artifacts", params={"limit": 200}
    ).json()["items"]
    assert all(artifact["kind"] != "structure" for artifact in artifacts)


def test_structure_proposal_partial_accept(app, client, project):
    """只勾选一条时，其余结构变更不应生效。"""
    created = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "甲"}, {"title": "乙"}]},
    ).json()
    first, second = created

    proposal = _make_structure_proposal(
        app,
        project["id"],
        [
            {"action": "rename", "unit_id": first["id"], "title": "甲改"},
            {"action": "delete", "unit_id": second["id"]},
        ],
    )
    client.post(f"/api/proposals/{proposal['id']}/accept", json={"op_indices": [0]})

    units = {unit["id"]: unit for unit in _units_of(client, project["id"])}
    assert units[first["id"]]["title"] == "甲改"
    assert second["id"] in units, "未勾选的删除不应执行"


def test_structure_proposal_rejects_cycle(app, client, project):
    """把父级移进自己的子树会成环，必须整体拒绝且不留部分变更。"""
    created = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "父"}]},
    ).json()
    parent = created[0]
    child = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "子", "parent_id": parent["id"]}]},
    ).json()[0]

    proposal = _make_structure_proposal(
        app,
        project["id"],
        [
            {"action": "rename", "unit_id": parent["id"], "title": "先改名"},
            {"action": "move", "unit_id": parent["id"], "parent_id": child["id"]},
        ],
    )
    response = client.post(f"/api/proposals/{proposal['id']}/accept", json={})
    assert response.status_code == 409, response.text

    # 事务整体回滚：前一条重命名也不应留下
    units = {unit["id"]: unit for unit in _units_of(client, project["id"])}
    assert units[parent["id"]]["title"] == "父"
    assert units[parent["id"]]["parent_id"] is None
