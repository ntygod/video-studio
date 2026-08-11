# Video Studio Architecture V2

> 本文描述目标架构和演进边界。V2 采用纵向替换，不进行一次性重写。

## 1. 分层

```text
Product UI / Product Template
            ↓
Domain Pack
            ↓
Creative Kernel
            ↓
Task Runtime / Provider Runtime
            ↓
Repositories / SQLite / Media Store
```

### Creative Kernel

负责稳定、领域无关的能力：

- Project / CreativeUnit
- Artifact / ArtifactVersion
- ArtifactDefinitionRegistry
- Operation / OperationLog
- Dependency / Provenance / Freshness
- Asset / DerivedAsset
- Plan / Task / TaskAttempt
- EvaluationResult / PolicyDecision

### Domain Pack

视频领域包注册：

- 单元类型：act、sequence、scene、shot；
- Artifact 类型：brief、outline、screenplay、shot_plan、storyboard、timeline；
- schema、迁移器、差异器、合并策略；
- 确定性验证规则和 LLM 评估器；
- 上下游依赖规则；
- UI renderer 和编辑器描述；
- Planner 规则与 Prompt 版本。

### Product Template

只负责编排用户体验，不拥有底层数据真相。例如“从剧本生成分镜预览”由模板触发动态 Task Graph，而不是在代码中写死一套不可扩展的 workflow。

## 2. 写入路径

所有业务写入最终统一为：

```text
User / Agent
    ↓
Command
    ↓
Policy Check
    ↓
Precondition Check
    ↓
Operation Apply
    ↓
OperationLog + Domain Events
    ↓
Dependency / Freshness Propagation
```

禁止新增调用方直接通过 Repository 拼装跨实体写入。

每个 Operation 至少包含：

```text
id
type
target
arguments
preconditions
affected_entities
inverse_operation
risk_level
idempotency_key
status
```

JSON Patch 可以保留为底层实现细节，但不能继续作为用户和 Agent 的主要业务语言。

## 3. Artifact 内核

`ArtifactDefinitionRegistry` 为每个已知 kind 注册：

```text
kind
schema_version
payload_schema
validator
migration_handlers
differ
merge_strategy
summarizer
evaluator
renderer
```

未知 kind 仍可作为 `custom` 存储，但不得自动参与关键生产链路。

派生产物必须记录：

```text
ArtifactDependency
    upstream_version_id
    downstream_artifact_id
    dependency_type

ArtifactProvenance
    input_version_ids
    provider/model
    prompt_version
    parameters
    seed
    task_attempt_id

ArtifactFreshness
    fresh | stale | blocked | needs_review
    reason
    detected_at
```

当上游产生新版本时，系统沿依赖图传播 stale 状态，但不自动删除或覆盖下游结果。

## 4. Task Runtime

Agent、LLM、媒体和渲染统一进入耐久执行层：

```text
Plan
  └── Task Graph
        └── Task
              └── TaskAttempt
```

标准阶段：

```text
Intent Analysis
→ Plan
→ Execute
→ Validate
→ Evaluate
→ Repair（有界）
→ Apply / Propose / Review
```

所有 Task 具备：

- 持久化状态机；
- 幂等键；
- lease 与 heartbeat；
- retry policy；
- timeout 与 cancel；
- checkpoint；
- cost/usage；
- event log；
- crash resume。

FastAPI 最终只负责 API 与流式事件；worker 进程负责 Agent、模型、媒体和渲染。单机阶段仍可部署在同一机器上。

## 5. Context Engine

上下文不再只是“搜索结果拼接”，而要区分：

- Canonical Facts：批准的角色、世界观、品牌约束；
- Draft Content：仍可能变化的稿件；
- Conversation Memory：用户偏好和已确认决定；
- Task Context：当前任务所需的最小输入；
- Reference Assets：图片、音视频和文档；
- Conflicts：多个来源之间的不一致。

每条上下文都应带来源、版本、权威级别和更新时间。

## 6. Provider Runtime

媒体 Provider 统一为异步协议：

```text
submit
poll
cancel
download
normalize
probe
```

外部任务 ID、原始响应、下载状态、文件 hash、输入资产、prompt 版本和参数必须持久化。服务重启后能够继续轮询，幂等重试不得重复创建业务 Asset。

## 7. UI 状态模型

保留当前健康边界：

- React Query 管理服务端状态；
- Zustand 只保存纯 UI 状态；
- 当前视图和选中单元保存在 URL。

V2 UI 新增四类一等状态：

- 计划与执行轨迹；
- 依赖和影响范围；
- Freshness / blocked / review 状态；
- 质量评估和下一步建议。

## 8. 兼容策略

- 不进行大爆炸重写；
- 每次只迁移一条完整用户流程；
- 新旧模块可短期并存，但同一实体只能有一个写入真相；
- 优先增加新表，修改已有表必须通过 Alembic；
- 每个迁移阶段都必须有 Golden Project 和回滚方案；
- 旧入口在新入口达到验收标准后删除，不长期保留双实现。
