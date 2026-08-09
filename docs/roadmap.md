# Video Studio 施工计划（前后端）

> **前提**：不考虑向后兼容。可以自由改 API、改 schema、删库重建。
> 数据库变更**不写迁移**——改完 `app/store/models.py` 后直接删掉 `data/studio.db*` 三个文件重新生成。
>
> **本文是工单**：每项任务给出文件路径、签名、契约与验收标准，按编号顺序执行即可。
> 上游文档：`docs/ui-redesign.md`（UI 方案，P0 已完成）、`docs/design-tokens.md`（设计令牌）。

---

## 0. 已确认的决策

| # | 决策 | 影响 |
|---|---|---|
| A | **组件库**：保留 antd 做控件，容器/布局 Tailwind 自绘，已删 shadcn | P0 已落地 |
| B | **视觉**：暗色优先，亮色可选 | P0 已落地 |
| C | **AI 权限边界**：**追加直接做，覆盖走提案** | 见 §1.2，引入"回合撤销"需求 |
| D | **工作流（workflow）**：**删掉** | 见 T0.4 |

### 决策 C 的展开

| 操作 | 走法 | 落库形态 |
|---|---|---|
| 新建稿件 | 直接做 | `artifact.source="ai"`，首版 `status="draft"` |
| 新建创作单元 | 直接做 | 记入所属 turn，可整回合撤销 |
| 生成图片/视频/配音 | 直接做 | 派发 job，产物为新 asset |
| **修改已有稿件内容** | **提案** | `change_proposals` 表，用户逐条采纳 |
| **删除 / 移动 / 重构结构** | **提案** | 同上 |

因为 AI 现在会直接写入，**必须配套"撤销本回合"**：`agent_turns` 记录该回合创建的所有实体 id，一键回滚。见 T1.4 / T1.8。

### 仍待你确认的一项

**视频 provider 用哪家？** `app/integrations/media/client.py` 现在只有 `grok2api` 和 `openai` 两个分支，且假设**同步返回 URL**。真实视频 API 基本都是"提交 → 轮询 → 下载"，各家字段名不同。
T2.5 里我给了通用的 `MediaProvider` 协议骨架，但具体适配器需要你补上目标服务的接口文档。**在此之前 T2.5 只能实现协议层 + 现有两个同步分支的包装。**

---

## 1. 目标架构

### 1.1 Agent = 工具调用循环（替换一次性问答）

现在 `app/application/conversations.py:33` 把整个项目 JSON + 作用域内全部 artifact payload 塞进 system prompt，一次 `chat_json` 拿回 `{assistant_message, proposals}`。

改成：Agent 拿到一个**精简的初始上下文**和一组**工具**，自己决定读什么、分几步做。

```
用户消息 + context_refs
   ↓
[初始上下文：项目摘要 + 选中单元摘要 + 钉住的圣经条目]
   ↓
循环（最多 12 步）：
   LLM → 请求工具调用？
     是 → 执行工具 → 结果回填 → 继续
     否 → 输出最终回复 → 结束
   ↓
SSE 实时推送每一步
```

**这一个改动同时解决三件事**：上下文不再爆炸（按需拉取）、运行轨迹有内容可展示（每次工具调用一行）、长篇可用。

### 1.2 Job 引擎 = 有界工作池 + 协作式取消

替换 `app/application/job_engine.py` 的"每任务一裸线程、无上限"。

### 1.3 媒体 = 相对 URI + ffprobe 探测 + 缩略图 + 异步 provider

### 1.4 数据层 = 分页 + FTS5 + 修 N+1

---

## 2. 数据库最终 schema 变更

一次性列出，**在 Phase 1 开始前把 `models.py` 改到位，然后删库**。后续阶段不再动 schema。

### 删除

```python
# app/store/models.py —— 整个类删掉
class WorkflowRow(Base): ...      # 决策 D
class NodeRunRow(Base): ...       # 死概念，创建后从不更新
```

### 新增

```python
class AgentTurnRow(Base):
    __tablename__ = "agent_turns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="SET NULL"), nullable=True
    )
    user_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assistant_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    # running | succeeded | failed | canceled | reverted
    context_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 本回合直接创建的实体，用于整回合撤销：
    # [{"type":"artifact"|"unit"|"asset"|"job","id":"..."}]
    created_entities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class AgentStepRow(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (Index("ix_steps_turn_seq", "turn_id", "seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_turns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # tool | message | error
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    # running | ok | failed
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
```

### 修改现有表

```python
class JobRow(Base):
    # 新增
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    parent_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # progress 语义统一为 0–1（见 T2.3）


class ArtifactRow(Base):
    # 新增：乐观锁，现在只有 project 有 revision
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AssetRow(Base):
    # 新增：缩略图相对路径，空串表示未生成
    thumb_uri: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # uri 语义变更：改存相对路径（"<project_id>/<...>"），不再存绝对文件系统路径
```

### FTS5 虚拟表（Phase 3 建，`create_schema()` 里用原生 SQL）

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
    unit_id UNINDEXED, project_id UNINDEXED, title, summary, continuity_summary,
    tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
    artifact_id UNINDEXED, project_id UNINDEXED, unit_id UNINDEXED, name, body,
    tokenize='trigram'
);
```

> `tokenize='trigram'` 是为中文——默认 unicode61 分词器对中文无效，只会按整段匹配。

---

## Phase 0 · 收尾与清理（0.5 天）

P0 遗留 + 决策 D 的删除。**必须先做完，否则后面都建在半截地基上。**

### T0.1 执行 P0 未跑完的命令

```bash
cd web
rm -f src/shared/components/emotion-curve.tsx src/__patch_test__.ts \
      src/shared/lib/canvas-theme.test.ts components.json tsconfig.tsbuildinfo
rmdir src/shared/components
pnpm install
pnpm build
```

**验收**：`pnpm build` 通过；记录产物体积，与改动前对比应下降 ≥30%。

### T0.2 跑一遍测试

```bash
cd web && pnpm test          # 需要 Node ≥ 22.6（TS 类型剥离）
cd .. && .venv/Scripts/python -m pytest tests/ -v
```

**验收**：前端 2 个测试文件全绿；后端 `test_open_core.py` 全绿（T0.4 会让 workflow 相关的测试失败，一并改）。

### T0.3 删库重建

先做完 §2 的 `models.py` 全部改动，然后：

```bash
rm -f data/studio.db data/studio.db-shm data/studio.db-wal
.venv/Scripts/python start_server.py    # 自动 create_all 重建
```

### T0.4 删除 workflow（决策 D）

删除清单：

| 文件 | 动作 |
|---|---|
| `app/domain/workflow.py` | 删 |
| `app/api/routes/workflows.py` | 删 |
| `app/application/workflows.py` | 删 |
| `app/store/models.py` | 删 `WorkflowRow`、`NodeRunRow` |
| `app/store/repositories.py` | 删 `WorkflowRepository`；删 `JobRepository.create_node_run` |
| `app/store/unit_of_work.py` | 删 `self.workflows` |
| `app/api/routes/__init__.py` | 移除 workflows router |
| `app/main.py:29` | 删 `seed_workflows` 调用与 import |
| `app/domain/__init__.py` | 移除 workflow 导出 |
| `app/application/job_engine.py` | 删 `_run_workflow`、`_execute` 里的 `workflow` 分支 |
| `web/src/services/api/system.ts` | 删 `listWorkflows` 等 4 个函数与 `Workflow` 类型 |
| `web/src/services/api/types.ts` | 删 `Workflow` / `WorkflowDefinition` |
| `tests/test_open_core.py` | 删 `test_workflows_and_assets` 里的 workflow 部分，保留 asset 部分 |

**验收**：全仓库 `grep -ri workflow` 只剩 `CreativeProject.workflow_id` 这个开放文本字段（保留，它只是个标识符）。

---

## Phase 1 · Agent 内核（2 周）

**目标：Agent 真的像 Agent —— 会读、分步、看得见、打不爆上下文。**

### 后端

#### T1.1 LLM 客户端重写（2 天）

拆分 `app/integrations/llm/client.py`：

```
app/integrations/llm/
  __init__.py          工厂 build_adapter(provider) -> LLMAdapter
  base.py              协议与数据类
  openai_adapter.py
  anthropic_adapter.py
  json_protocol.py     不支持原生 tool call 时的回退
```

`base.py`：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]      # JSON Schema

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ChatChunk:
    kind: Literal["token", "tool_call", "usage", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict[str, int] | None = None

class LLMAdapter(Protocol):
    supports_native_tools: bool
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]: ...
```

要点：
- OpenAI 走 `stream=True` + `tools`，逐 `delta` 解析；tool call 的 `arguments` 是分片到达的，需要按 `index` 累积
- Anthropic 走 `/v1/messages` + `stream=true`，事件类型 `content_block_delta`（`text_delta` / `input_json_delta`）
- `json_protocol.py`：把 tools 渲染进 system prompt，要求模型输出 `{"tool":"名","args":{...}}` 或 `{"final":"回复"}`，逐行解析
- **超时 600s → 120s**（`client.py:60,79`），失败快速反馈
- 删掉 `chat_json` 的"重试 3 次修 JSON"（有 tool schema 后不需要）
- `extract_json` 保留给 `json_protocol.py` 用

**验收**：三个适配器各写一个 fake-server 单测，验证 token 流与 tool call 解析；断网时 5 秒内抛错而不是挂 600 秒。

#### T1.2 Agent 工具集（2 天）

新增 `app/application/agent/tools.py`。

```python
@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    mutates: bool          # True 时记入 turn 的 created_entities

@dataclass
class ToolContext:
    uow: Any
    project_id: str
    unit_id: str | None
    turn_id: str
    settings: Any
    job_engine: Any
```

工具清单（**返回值必须精简**，这是控制上下文的关键）：

| 工具 | 参数 | 返回 | 类型 |
|---|---|---|---|
| `list_units` | `parent_id?`, `depth=1` | `[{id,title,unit_type,stage,has_artifacts,child_count}]` | 只读 |
| `read_unit` | `unit_id` | `{...unit, artifacts:[{id,kind,name,version}], asset_count}` | 只读 |
| `read_artifact` | `artifact_id`, `path?` | `path` 为空返回**摘要**（顶层键 + 各自长度）；给了 `path` 才返回该子树全文 | 只读 |
| `search` | `query`, `kind?`, `limit=10` | `[{type,id,title,snippet}]` | 只读 |
| `read_bible` | `section: characters\|world\|style\|all` | 对应片段 | 只读 |
| `list_assets` | `unit_id?`, `kind?` | `[{id,kind,name,mime_type,width,height,duration}]`（**不含 uri 与二进制**） | 只读 |
| `write_artifact` | `unit_id?`, `kind`, `name`, `payload` | `{artifact_id, version}` | 追加 |
| `create_units` | `units:[{title,unit_type,parent_id?,summary?}]` | `[{id,title}]` | 追加 |
| `generate_media` | `kind: image\|video\|voice`, `prompt`, `unit_id?`, `params?` | `{job_id}` | 追加 |
| `propose_change` | `artifact_id`, `operations:[{op,path,value}]`, `title`, `rationale` | `{proposal_id}` | 提案 |
| `propose_restructure` | `changes:[{action,unit_id,...}]`, `title`, `rationale` | `{proposal_id}` | 提案 |

**`read_artifact` 的两段式设计是刻意的**——不给 `path` 只回摘要，逼 Agent 精确取用，避免一次把整份剧本拉进上下文。

#### T1.3 Agent 循环（2 天）

新增 `app/application/agent/loop.py`：

```python
MAX_STEPS = 12

def run_turn(
    database,
    settings,
    job_engine,
    turn_id: str,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    """
    读取 turn 记录 → 组装上下文 → 循环调用 LLM 与工具 → 落库 → emit 事件。
    每一步都要检查 turn.status 是否被置为 canceled（协作式中断）。
    """
```

事件形状（也是 SSE 的载荷）：

```python
{"type": "step.start", "step_id": "...", "seq": 1, "tool": "read_unit", "args_preview": "第7章"}
{"type": "step.done",  "step_id": "...", "ok": True, "duration_ms": 210, "summary": "读取 第7章 · 剧本 v3"}
{"type": "token",      "text": "我先看一下"}
{"type": "proposal",   "proposal": {...}}
{"type": "entity",     "entity": {"type": "artifact", "id": "...", "name": "..."}}   # 追加操作产出
{"type": "error",      "message": "...", "recoverable": False}
{"type": "done",       "message_id": "...", "usage": {"prompt": 3200, "completion": 480}}
```

新增 `app/application/agent/context.py`：

```python
def build_initial_context(uow, project_id, unit_id, context_refs) -> tuple[str, int]:
    """
    只组装：
      - 项目一句话摘要（title + brief.concept + brief.objective）
      - 当前单元摘要（title + summary + continuity_summary）
      - context_refs 里显式点名的实体
      - 钉住的圣经条目
    返回 (上下文文本, 预估 token 数)。
    绝不再全量转储 artifacts。
    """
```

新增 `app/application/agent/prompts.py`：系统提示词，说明工具用法、追加/提案的边界（决策 C）、以及"先读再写"的要求。

**同时修复 X2**：LLM 失败时写入一条 `kind="error"` 的 step 并把 turn 置 `failed`，不再留下孤儿用户消息。

#### T1.4 回合持久化与撤销（1 天）

`app/store/repositories.py` 新增 `AgentTurnRepository`：

```python
class AgentTurnRepository:
    def create(self, conversation_id, project_id, unit_id, context_refs) -> dict
    def get(self, turn_id) -> dict                    # 含 steps
    def list(self, conversation_id) -> list[dict]
    def add_step(self, turn_id, kind, tool_name, arguments) -> dict
    def finish_step(self, step_id, status, result, summary, error="") -> dict
    def record_entity(self, turn_id, entity_type, entity_id) -> None
    def set_status(self, turn_id, status, error="") -> dict
    def revert(self, turn_id) -> dict
    """删除本回合直接创建的实体（artifact / unit / asset），
       取消本回合派发但未完成的 job，把 turn 置为 reverted。
       已被用户后续编辑过的实体跳过并在返回值里报告。"""
```

**决策 C 的必要配套**：AI 直接写入后必须能一键回退整个回合。

#### T1.5 SSE 端点（1 天）

改写 `app/api/routes/conversations.py`：

```
POST /api/conversations/{id}/turns
  body: {content: str, context_refs: [{type, id}], mode?: str}
  → 201 {turn_id, user_message}
  立即返回，在后台线程执行 run_turn

GET  /api/conversations/{id}/stream?turn_id={id}
  → text/event-stream
  重连时用 Last-Event-ID 从 agent_steps 补发历史事件

POST /api/turns/{turn_id}/cancel   → {ok}
POST /api/turns/{turn_id}/revert   → {reverted:[...], skipped:[...]}
GET  /api/turns/{turn_id}          → {turn, steps}
```

删除旧的 `POST /api/conversations/{id}/messages`。

SSE 实现要点：用 `queue.Queue` 做进程内事件总线，`StreamingResponse` 消费；每 15 秒发一个 `: keepalive` 注释帧防代理超时。

#### T1.6 提案预览与逐条采纳（1 天）

改写 `app/api/routes/proposals.py`：

```
GET  /api/proposals/{id}/preview
  → {before: {}, after: {}, field_diffs: [{path, op, before, after}]}

POST /api/proposals/{id}/accept
  body: {op_indices?: int[]}          # 省略表示全部
  → {proposal, artifact_id, version}
```

`app/application/artifacts.py` 的 `accept_proposal` 增加 `op_indices` 参数，只应用选中的 operations。

#### T1.7 修 D1：深合并（0.5 天）

`app/application/artifacts.py:94-104`。现在对 brief/project_bible 做 `CreativeBrief.model_validate(proposed_payload)`——**AI 给局部 payload 会把未提及字段全部重置为默认值**。

改为：

```python
def deep_merge(base: dict, patch: dict) -> dict:
    """dict 递归合并；list 与标量整体替换。"""
```

先 `deep_merge(当前 payload, proposed_payload)` 再 `model_validate`。

**验收**：写一个测试——brief 已有 5 个字段，提案只含 `concept`，采纳后另外 4 个字段保持不变。

#### T1.8 修 S2：artifacts.list N+1（0.5 天）

`app/store/repositories.py:390-395` 现在是 `[self.get(row.id) for row in rows]`，每条再查一次版本。改成一次 join：

```python
def list(self, project_id, unit_id=None, include_payload=True) -> list[dict]:
    query = (
        select(ArtifactRow, ArtifactVersionRow)
        .outerjoin(ArtifactVersionRow, ArtifactRow.current_version_id == ArtifactVersionRow.id)
        .where(ArtifactRow.project_id == project_id)
    )
    ...
```

新增 `include_payload=False` 时不解析 `payload_json`，只回元信息——列表场景不需要正文。

### 前端

#### T1.F1 SSE 管理器（1 天）

新增 `web/src/services/stream/`：

```
sse-client.ts      单例 EventSource 管理，指数退避重连，Last-Event-ID 续传
use-turn-stream.ts hook：订阅某个 turn，把事件归并成 {steps[], text, proposals[], status}
```

后端未就绪时降级：轮询 `GET /api/turns/{id}`。

#### T1.F2 Agent 面板重写（3 天）

`web/src/features/agent/components/`：

```
agent-panel.tsx        容器（已存在，重写）
run-trace.tsx          运行轨迹：可折叠步骤行 + 状态点 + 耗时 + 单步重试
context-bar.tsx        上下文条：chip 列表 + 添加 + token 预估
mention-picker.tsx     输入框内 @ 唤起的实体选择器
proposal-card.tsx      内联提案卡：字段级 before→after + 逐条勾选
composer.tsx           已存在，增加模式切换与停止按钮
turn-actions.tsx       「撤销本回合」
```

运行轨迹的视觉规格见 `docs/ui-redesign.md` §4.2(a)；上下文条见 §4.2(b)；提案卡见 §4.2(c)。

#### T1.F3 舞台自适应布局（1 天）

`workspace-shell.tsx`：无 artifact 时 Agent 居中（720px 单栏），出现第一份稿件后转三栏，顶部给「已切换 · 撤销」。切换只发生一次，之后尊重手动选择（存 localStorage）。

#### T1.F4 数据层跟进（0.5 天）

`services/queries/use-conversations.ts` 改造：`useSendMessage` → `useStartTurn` + `useTurnStream`；删除旧的阻塞式 `sendMessage`。

### Phase 1 验收

- [ ] 首 token < 2s 可见
- [ ] 20 章项目连续 20 轮对话，单轮 prompt token < 8k（现在线性爆炸）
- [ ] 任意时刻能看到 Agent 正在执行哪个工具、已耗时多久
- [ ] 刷新页面后运行轨迹完整重放
- [ ] LLM 失败时消息流里有明确错误行，不静默卡住
- [ ] 提案能只采纳其中 2 条，未选中的 operation 不生效
- [ ] brief 提案只含 1 个字段时，其余字段不被清空
- [ ] AI 建了 5 个单元后点「撤销本回合」，5 个单元全部消失
- [ ] 点「停止」后 3 秒内循环终止

---

## Phase 2 · 生产内核（2 周）

**目标：自由创作图片和视频 —— 产品承诺里目前完全没有 UI 的部分。**

### 后端

#### T2.1 Job 引擎重写（3 天）

`app/application/job_engine.py` → 拆成 `app/application/jobs/`：

```
engine.py      有界工作池
queue.py       DB 队列认领与 lease
handlers/      按 job_type 分文件：llm.py media.py tts.py render.py batch.py
```

```python
class JobEngine:
    def __init__(self, database, settings, media_store, workers: int = 4): ...
    def start(self) -> None:
        """启动固定数量 worker 线程 + 一个 lease 回收线程。"""
    def submit(self, job_id: str) -> None:
        """仅入队，不再直接开线程。"""
    def stop(self, timeout: float = 10) -> None: ...
```

认领语句（保证不重复认领）：

```sql
UPDATE jobs
   SET status='running', worker_id=:wid, lease_until=:now+60, updated_at=:now,
       attempt=attempt+1
 WHERE id=(SELECT id FROM jobs WHERE status='queued'
           ORDER BY created_at LIMIT 1)
   AND status='queued'
RETURNING id;
```

**协作式取消（修 D2）**：所有 handler 接收 `should_cancel: Callable[[], bool]`，在每次外部请求前后、每次轮询、ffmpeg 每次进度回调时检查。现在 `_execute:63` 只在开始时检查一次，运行中的任务永远取消不掉。

**重试**：失败后若 `attempt < max_attempts` 置回 `queued`，退避 `2^attempt` 秒；到顶置 `failed`。

**恢复**：`recover()` 把 `lease_until < now` 的 running 任务打回 queued。

#### T2.2 任务 SSE（0.5 天）

```
GET /api/jobs/stream?project_id=
  event: job.progress {job_id, progress, status}
  event: job.event    {job_id, level, stage, message, progress}
  event: job.done     {job_id, status, result}
```

#### T2.3 修 X7：进度语义统一（0.5 天）

现在 `JobRow.progress` 是 0–1（`repositories.py:707,772` 两处各做一次 `>1 then /100` 的猜测式归一化），`JobEventRow.progress` 是 0–100 原样存。

**统一为 0–1**：删掉两处猜测归一化，所有调用方（`job_engine.py` 里的 `progress=80.0` 等）改成传 `0.8`；`add_event(progress=...)` 同样传 0–1。前端 `progressPercent()` 已按 0–1 处理，无需改。

#### T2.4 媒体管线（2 天）

`app/store/media_store.py`：

```python
def write_bytes(self, project_id, data, suffix, unit_id=None) -> tuple[str, str]:
    """返回 (相对 uri, sha256)。
    相对 uri 形如 "<project_id>/<unit_id>/<uuid>.png"，
    asset.uri 存 "/media/" + 相对 uri。修 D7。"""

def probe(self, relative_uri) -> dict:
    """ffprobe 探测 width/height/duration/codec，写进 asset.metadata。"""

def make_thumb(self, relative_uri, mime_type) -> str:
    """图片缩放到 640px 长边；视频抽 1s 处的帧；音频算 200 点波形峰值存 JSON。
    返回缩略图相对 uri，写进 asset.thumb_uri。"""
```

新增路由 `app/api/routes/media.py`：

```
GET /api/assets/{id}/thumb?w=320    → 缩略图，无则回落原图
```

**改完后删除前端的兼容分支**：`web/src/services/api/http.ts` 里 `mediaUrl()` 那段从绝对路径截 `data/media/` 的逻辑（P0 的临时兜底）。

#### T2.5 异步 media provider（1.5 天，**依赖你提供目标服务文档**）

`app/integrations/media/`：

```python
class MediaProvider(Protocol):
    def submit(self, prompt: str, params: dict) -> str: ...          # → task_id
    def poll(self, task_id: str) -> tuple[str, float]: ...           # → (status, progress 0-1)
    def fetch(self, task_id: str) -> bytes: ...

class SyncProviderAdapter(MediaProvider):
    """把现有同步实现包成异步协议：submit 直接调用并缓存结果。"""
```

轮询进度写进 job events，前端任务坞实时可见。
支持按请求选模型（现在 `client.py:27` 硬取 `models[0]`）。
支持参考图（image-to-image / image-to-video）。

#### T2.6 批量生成（0.5 天）

```
POST /api/projects/{id}/generate/batch
  body: {unit_ids: str[], capability: "image"|"video"|"voice",
         prompt_template: str, params: {}}
  → 201 {parent_job_id, child_job_ids: str[]}
```

`prompt_template` 支持 `{unit.title}` / `{unit.summary}` / `{bible.style.visual_direction}` 占位符。
父任务进度 = 子任务完成比例。

#### T2.7 零散修复（0.5 天）

| 编号 | 位置 | 修法 |
|---|---|---|
| X4 | `api/routes/generate.py:30` | 硬编码 `"unit_id": None` → 从请求体读 `unit_id` |
| X6 | `api/routes/jobs.py:51` | 裸 `RuntimeError` → `ConflictError`（已有 409 handler） |
| D6 | `api/routes/providers.py:31` | `ProviderPatch` 增加 `models` 字段；`ProviderRepository.update` 支持全量替换模型列表 |
| — | `api/errors.py` | 补一个兜底 handler：未捕获异常 → 500 + `{detail}`，同时记结构化日志，不再回栈给前端 |

#### T2.8 provider 连接测试（0.5 天）

```
POST /api/provider-profiles/{id}/test
  → {ok: bool, latency_ms: int, detail: str, models_seen?: str[]}
```
llm 发一个 1-token 请求；image/video 只探活 base_url。

### 前端

#### T2.F1 分镜墙（4 天）—— 本阶段核心

新增路由 `web/src/app/(workspace)/projects/[id]/board/page.tsx`，组件在 `features/canvas/board/`：

```
board-view.tsx        网格/列表切换、批量工具条
shot-card.tsx         缩略图 / 编号 / 景别运镜 / 描述 / 时长 / 状态点
shot-candidates.tsx   一个镜头多个候选时的圆点切换选片
batch-generate.tsx    多选后的批量生成弹窗（选能力、prompt 模板、参数）
generation-overlay.tsx 生成中骨架 + 百分比
```

交互规格见 `docs/ui-redesign.md` §4.4。要点：
- 卡片 = 镜头单元 + 它的候选素材
- 悬停操作：生成图 / 生成视频 / 重生成 / 上传替换 / 选版本
- 多选 → 批量生成，进度回到任务坞，**不弹 toast、不跳页**
- 拖拽重排 → `PATCH unit.order_index`
- 列表模式供几十上百镜头时通读

#### T2.F2 素材库重做（1.5 天）

`features/canvas/components/media-view.tsx` 重写：缩略图网格、筛选（类型/来源/是否已使用）、视频悬停预览、音频波形、血缘链（哪个 prompt 与 job 产出、被哪个镜头使用）、拖拽到分镜卡片。

#### T2.F3 任务坞接 SSE（0.5 天）

`features/jobs/components/job-dock.tsx` 改用 `useJobStream`，去掉轮询；子任务按 `parent_job_id` 折叠成任务树。

#### T2.F4 设置页改能力优先（1 天）

`app/(user)/settings/page.tsx` 重写为一行一种能力（文本/图片/视频/配音）+ 当前渠道 + 连接测试按钮 + 切换。模型列表改**表格增删行**，不再让用户手写 JSON（现在 `EMPTY_FORM.models_json` 是个裸 JSON 字符串）。

### Phase 2 验收

- [ ] 从一句话到一张能看的分镜图，全程不离开工作台
- [ ] 选 8 个镜头批量生成，一次点击完成，任务坞看到 1 父 + 8 子任务
- [ ] 运行中的任务点取消，5 秒内真的停止（当前完全无效）
- [ ] 50 个并发任务不会开 50 个线程，worker 数恒定
- [ ] 任务失败自动重试 2 次后才标记失败，事件日志里能看到每次尝试
- [ ] 素材库 200 张图滚动流畅（缩略图 + 懒加载）
- [ ] 杀掉服务再启动，运行中的任务被正确恢复
- [ ] 设置页能测出某个渠道的连通性与延迟

---

## Phase 3 · 长篇内核（1.5 周）

**目标：500 单元的项目不卡、不迷路、不失忆。**

### 后端

#### T3.1 分页与瘦身（1.5 天）

```
GET /api/projects/{id}
  → 只返回项目本身 + {unit_count, artifact_count, asset_count,
                      pending_proposal_count, last_activity}
    不再内嵌 units / artifacts / pending_proposals（修 S3）

GET /api/projects/{id}/units?parent_id=&depth=1&limit=200&cursor=
GET /api/projects/{id}/artifacts?unit_id=&kind=&include_payload=false&limit=50&cursor=
GET /api/projects/{id}/assets?unit_id=&kind=&limit=50&cursor=
GET /api/jobs?project_id=&status=&limit=50&cursor=
```

游标用 `(created_at, id)` 复合，避免 offset 分页的漂移。

#### T3.2 FTS5 检索（1 天）

`app/store/database.py` 的 `create_schema()` 里建 §2 的两张虚拟表 + 同步触发器（insert/update/delete）。

```
GET /api/projects/{id}/search?q=&type=unit|artifact|all&limit=20
  → [{type, id, title, snippet, unit_id}]
```

同时作为 Agent `search` 工具的后端。

#### T3.3 上下文压缩（1.5 天）

新增 `app/application/agent/compaction.py`：

1. **单元连贯性摘要**：`CreativeUnit.continuity_summary` 字段已存在但**从来没人写**。在单元下的稿件被采纳/定稿时，派发一个轻量 llm job 生成 2–3 句摘要写入。Agent 读父级/兄弟单元时优先用摘要而非全文。
2. **对话滚动摘要**：单个 conversation 超过 N=20 轮时，把最早的 10 轮压缩成一条 `role="system"` 的摘要消息，原消息保留但不再进 prompt。
3. **钉住条目**：`ProjectSettings` 增加 `pinned_refs: list[{type,id}]`，每轮强制注入。

#### T3.4 项目列表补字段（0.5 天）

`GET /api/projects` 增加 `cover_asset_id`（该项目最新的 render 或 image 资产）、`pending_proposal_count`、`last_activity`。用一次聚合查询，不要 N+1。

### 前端

#### T3.F1 结构树虚拟化（1 天）

`pnpm add @tanstack/react-virtual`（P0 时刻意没装，因为当时用不上）。
`features/structure/components/unit-tree.tsx` 改为虚拟化列表，扁平化后渲染，保留折叠状态。

#### T3.F2 结构区增强（1.5 天）

筛选（未完成 / 有提案 / 已锁定 / 按类型）、搜索接 FTS、拖拽重排与改父级、多选 → 批量交给 Agent（自动填进上下文条）。

#### T3.F3 圣经面板（1 天）

`features/structure/components/bible-panel.tsx`：角色/世界/风格常驻入口，浮层展示，每项可「📌 钉到上下文」。钉住状态写 `ProjectSettings.pinned_refs`。

#### T3.F4 项目库卡片（0.5 天）

用上 T3.4 的封面图、进度环、待处理提案角标、最近活动。

### Phase 3 验收

- [ ] 500 单元结构树滚动 60fps
- [ ] 单元切换首屏 < 300ms
- [ ] 连续 30 轮对话，prompt token 保持平稳不增长
- [ ] 1000 条稿件全文搜索 < 100ms
- [ ] `GET /projects/{id}` 响应体 < 5KB（现在会随项目线性增长到 MB 级）

---

## Phase 4 · 成片（1.5 周）

### 后端

#### T4.1 修时间线编译器（2 天）

`app/application/timeline_service.py` 三个 bug：

| 行 | 问题 | 修法 |
|---|---|---|
| `:46` | `"asset_id": asset["uri"]` 存的是路径不是 id（D4） | 存真实 `asset["id"]`；`timeline_render._resolve` 改为按 id 查 asset 再取路径 |
| `:79` | 所有 voice clip `start=0, duration=cursor` 全部重叠（D5） | 按顺序排布，或按 `decision.unit_id` 对齐到对应视频片段 |
| `:29` | 取最后一个 `edit_plan` artifact | 按状态择优：`approved` > `locked` > 最新 `draft` |

另外：clip 时长改用 `asset.metadata.duration`（T2.4 已探测），不再用 AI 猜的数字；`clip.metadata` 补 `{unit_id, shot_index}` 供前端映射回镜头。

#### T4.2 渲染进度（1 天）

`app/application/timeline_render.py`：ffmpeg 加 `-progress pipe:1`，解析 `out_time_ms` 与总时长换算成 0–1，写进 job events。现在渲染是 0% 直接跳 100%。

#### T4.3 版本 diff 与回滚（1 天）

```
GET  /api/artifact-versions/{a}/diff/{b}
  → {field_diffs: [{path, op: "add"|"remove"|"replace", before, after}]}
POST /api/artifacts/{id}/restore/{version_id}
  → 以目标版本内容追加一个新版本（不删历史）
```

结构化 diff（按字段路径对齐），不是文本 diff。

#### T4.4 版本状态机（0.5 天）

`ArtifactRepository.set_status` 现在允许任意跳转（locked → draft 也行）。加约束：
`draft → proposed → approved → locked`，只能前进；`locked` 为终态，要改必须新建版本。

### 前端

#### T4.F1 时间线视图（3 天）

新增 `/projects/[id]/timeline`，组件在 `features/canvas/timeline/`：

```
timeline-view.tsx    播放器 + 轨道容器
player.tsx           16:9 / 9:16 预览
track-row.tsx        单条轨道
clip-block.tsx       片段，支持拖动改时长与重排
ruler.tsx            时间刻度
```

v1 范围：拖动改时长、拖动重排、静音/独奏、音量、点击 clip 跳到对应镜头卡。
**不做**关键帧曲线（`Keyframe` 结构留着，UI 后置）。
自绘（div + transform），**不引第三方时间线库**。

#### T4.F2 版本视图（1 天）

新增 `/projects/[id]/versions`：左侧版本列表（带 AI/用户/任务来源徽标），右侧并排结构化 diff，支持回滚。

#### T4.F3 故事视图分体裁渲染（2 天）

`features/canvas/story/renderers/`：

```
outline-renderer.tsx     可折叠嵌套大纲，拖拽重排
script-renderer.tsx      剧本排版：场景标题、角色名居中、对白缩进、动作正文
shot-plan-renderer.tsx   镜头表格（与分镜墙共用卡片组件）
document-renderer.tsx    analysis / generated 的文档流
fallback-renderer.tsx    未知 kind → 现有的 ArtifactContentView
```

配套**块级 AI 改写**：悬停任意段落/场景/镜头浮出 `✨`，点击把该块作为上下文塞进 Agent 输入框并预填「改写这段：…」。

### Phase 4 验收

- [ ] 能预览、微调、导出成片
- [ ] 渲染进度实时可见，不是 0% 跳 100%
- [ ] 时间线上点一个 clip 能跳到对应镜头
- [ ] voice 轨道不再全部重叠
- [ ] 能对比任意两个版本并回滚
- [ ] 剧本渲染出来像剧本，不是 key-value 转储
- [ ] 已定稿（locked）的版本无法被改回 draft

---

## Phase 5 · 打磨（1 周）

| 编号 | 任务 |
|---|---|
| T5.1 | `⌘K` 命令面板：跳单元、跳视图、执行动作、搜索 |
| T5.2 | 全键盘：树上下导航、`Space` 多选、`Esc` 关浮层、焦点陷阱 |
| T5.3 | a11y：`aria-live` 播报 Agent 流式与任务完成；所有图标按钮补 `aria-label` |
| T5.4 | 空/错/载状态统一走 `EmptyState` / `ErrorPanel` / 骨架屏 |
| T5.5 | 平板适配（768–1280px 的两栏形态） |
| T5.6 | **关掉 `next.config.ts` 的 `typescript.ignoreBuildErrors`**（X9），修掉暴露出来的类型错误 |
| T5.7 | 后端结构化日志（JSON 行）+ 请求 ID 贯穿到 job 与 agent step |
| T5.8 | 补测试：Agent 循环、Job 引擎并发与取消、时间线编译、提案深合并、FTS 检索 |

---

## 汇总

| 阶段 | 内容 | 工期 | 阻塞关系 |
|---|---|---|---|
| **0** | 收尾清理 + 删 workflow + 改 schema 删库 | 0.5 天 | 无 |
| **1** | Agent 内核 | 2 周 | 依赖 0 |
| **2** | 生产内核 | 2 周 | 依赖 1（工具要能派发 job） |
| **3** | 长篇内核 | 1.5 周 | 依赖 1（search 工具） |
| **4** | 成片 | 1.5 周 | 依赖 2（媒体探测） |
| **5** | 打磨 | 1 周 | 依赖全部 |

**合计约 8 周**（单人）。阶段内前后端可并行，阶段间不建议乱序。

**第一件事**：Phase 0 的 T0.1（跑完 P0 没跑的构建）和 §2 的 schema 改动 —— 它们是后面所有事情的地基。

---

## 附：本计划修复的缺陷索引

| 编号 | 问题 | 修复位置 |
|---|---|---|
| D1 | 接受 brief/bible 提案会重置未提及字段 | T1.7 |
| D2 | 运行中的任务取消不掉 | T2.1 |
| D3 | 工作流只跑入口节点不会流动 | T0.4（删掉） |
| D4 | `clip.asset_id` 存的是路径不是 id | T4.1 |
| D5 | voice clip 全部重叠 | T4.1 |
| D6 | `ProviderPatch` 无 models 字段 | T2.7 |
| D7 | asset.uri 存绝对文件系统路径 | T2.4 |
| S1 | 每轮对话全量转储项目 | T1.3 |
| S2 | `artifacts.list()` N+1 | T1.8 |
| S3 | `GET /projects/{id}` 返回全部内容 | T3.1 |
| S4 | 线程数无上限 | T2.1 |
| S5 | 无全文检索 | T3.2 |
| X1 | 无流式，最坏 600s 无反馈 | T1.1 |
| X2 | LLM 失败留下孤儿用户消息 | T1.3 |
| X3 | 无 SSE | T1.5 / T2.2 |
| X4 | generate 硬编码 unit_id=None | T2.7 |
| X5 | 视频 provider 假设同步返回 | T2.5 |
| X6 | retry 裸 RuntimeError → 500 | T2.7 |
| X7 | 进度语义 0–1 与 0–100 混用 | T2.3 |
| X8 | 无版本 diff 接口 | T4.3 |
| X9 | `ignoreBuildErrors: true` | T5.6 |
| X10 | `NodeRunRow` 死概念 | T0.4（删掉） |
