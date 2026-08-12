# Video Studio V2 迁移计划

> 原则：先修可靠性，再建立内核；先完成一条纵向闭环，再扩展领域。  
> 执行方式：每个里程碑独立分支、独立验收、独立回滚。

## M0 · 可靠性基线

目标：让现有任务系统的状态、事件和重试行为可信。

### M0.1 任务事件流

- [x] SSE 从 `job_events` 增量读取；
- [x] 使用有界游标；
- [x] 增加持久化事件游标测试；
- [x] 支持 SSE id / Last-Event-ID 并在前端去重；
- [ ] 增加真实浏览器 EventSource 断线/重连测试；
- [ ] 为事件积压增加分页续读和监控。

### M0.2 手动重试状态机

- [x] 重试清理 `cancel_requested`、lease、worker、旧结果与错误；
- [x] attempt 归零并恢复自动重试预算；
- [x] 保留历史事件并追加 retry 审计；
- [ ] 统一 worker 终态清理逻辑。

### M0.3 后续可靠性

- [x] 修复 Agent 新建 Artifact 的可靠回合撤销；
- [x] Agent 回合进入固定 worker 与有界队列；
- [ ] 持久化流式输出 checkpoint；
- [ ] 把 Python 内存分页改为数据库游标分页；
- [ ] 建立通用故障注入基线。

**M0 验收：** 已取消任务可重试，事件可实时到达前端，现有测试全绿，无破坏性迁移。

## M1 · Artifact Definition Registry 与数据库迁移

- [x] 引入 Alembic baseline；
- [x] fresh 数据库升级，pre-Alembic 数据库保留数据并自动 stamp；
- [x] 建立 ArtifactDefinitionRegistry 与显式 schema migration handler；
- [x] 注册 brief、story_outline/story_graph、screenplay、shot_plan、timeline 与 project_bible；
- [x] 已知类型写入统一校验和规范化；
- [x] 非法载荷返回结构化 422，后台任务可观察失败；
- [x] 未知类型保持开放保存；
- [x] 暴露 `/api/artifact-definitions`；
- [ ] 为核心类型补领域完整性 Evaluator，归入 M5。

**M1 验收：** 核心 Artifact 有版本化 schema，旧库无需删除即可升级，开放类型仍兼容。

## M2 · CommandBus、OperationLog 与可靠补偿

### 已完成

- [x] `operation_logs` 与 Alembic 迁移；
- [x] CommandBus 支持业务幂等、前置条件、风险、影响实体和失败审计；
- [x] Artifact、提案、项目、单元、Asset、Timeline、Job 等核心写路径收口；
- [x] Agent mutating tools 只调用 Command API，并按 turn / step 幂等；
- [x] LLM、媒体、TTS、渲染与批量输出按 Job / 槽位幂等持久化；
- [x] 启动恢复 interrupted Operation 与媒体中断状态；
- [x] 暴露 OperationLog 查询和安全补偿 API；
- [x] 实现首批 Artifact、项目/单元编辑、批量建单元、素材作用域、提案与 queued Job inverse。

### 保留边界

- [ ] 项目、单元子树和媒体删除尚无完整关系快照一键恢复；
- [ ] 已执行或完成的外部任务不做“复活式撤销”；
- [ ] 新 mutating tool 必须继续提供幂等、失败与审计测试。

**M2 验收状态：** 核心写路径已收口；安全可逆操作具备确定性补偿，跨资源删除具备崩溃恢复边界。

## M3 · Dependency、Provenance、Freshness 与持久化修复

### 已完成

- [x] ArtifactDependency、AssetDependency、ArtifactProvenance 与 ArtifactFreshness；
- [x] Asset 删除保留 tombstone；
- [x] 上游 Artifact 前进递归传播 stale；
- [x] Asset / 单元删除递归传播 blocked；
- [x] 图拒绝自依赖、环、跨项目和超限边；
- [x] provenance、freshness、dependencies、dependents、impact 与项目级查询 API；
- [x] 工作台共享 Freshness 状态模型并阻止采用 stale / blocked 内容；
- [x] stale LLM 单点重新生成与 Timeline 素材修复 / 重编译；
- [x] Agent 直接、Turn 与 pinned 输入冻结及依赖登记；
- [x] 只读级联预览与确定性拓扑；
- [x] RegenerationPlan / Step 持久化执行；
- [x] Job 回调、启动与 reaper 的崩溃恢复；
- [x] 数据库 Step claim、多进程唯一派发、过期接管与迟到写入拒绝；
- [x] 失败 Plan Retry、attempt history、新幂等作用域与旧 Job 隔离；
- [x] 当前图 Replan、原子退休旧意图与唯一 lineage；
- [x] 工作台支持预览、创建、Start、Cancel、素材输入、Retry、Replan 与 lineage 导航；
- [x] Alembic head 达到 `20260812_0009`，fresh / legacy 升级测试覆盖。

### 下一步

- [ ] 可配置的部分成功继续策略；
- [ ] `needs_review` 的确认与继续流程；
- [ ] 已完成 Step 的自动补偿；
- [ ] 外部 Provider 强制取消与迟到输出策略；
- [ ] 500 节点压力、故障注入和生产数据库竞争基线；
- [ ] 生成 Asset 的 Freshness 节点模型；
- [ ] 故事结构 → 剧本 → 镜头 → 分镜等更多生产链自动登记；
- [ ] 项目库卡片显示项目状态与 active Plan 摘要。

详细设计：

- `docs/m3-freshness-and-regeneration.md`
- `docs/agent-explicit-production-inputs.md`
- `docs/regeneration-cascade-preview.md`
- `docs/regeneration-plan-execution.md`
- `docs/implementation-log-m3-20260812.md`

**M3 验收状态：** 精确输入、图传播、单点修复、级联预览、多进程执行、崩溃恢复、Retry、Replan 与工作台闭环已经成立。剩余工作是策略、性能、更多领域链和 Asset 生产图增强。

## M4 · Durable Task Runtime 与 Agent 2.0

### 已完成

- [x] Alembic `20260812_0010` 增加通用 RuntimePlan / RuntimeTask / RuntimeTaskAttempt / RuntimeTaskEvent；
- [x] Task DAG 验证、前驱释放与 blocked 传播；
- [x] 数据库级 claim、lease、heartbeat、checkpoint 与迟到写入拒绝；
- [x] Attempt history、retryable failure、backoff 与 max attempts；
- [x] timeout、Cancel 与 lease-expired crash recovery；
- [x] Plan 内单调事件序号和 `after_seq` 续读；
- [x] `TaskRuntime` 内部应用接口；
- [x] Plan、Task 与 Event 的只读可观察 API；
- [x] 并发、恢复、重试、超时、取消、DAG、事件和 fresh / legacy 迁移测试。

### 下一步

- [ ] Agent tool-loop 的持久化 checkpoint；
- [ ] 跨 Attempt 稳定 logical tool call ID 与 Operation 幂等键；
- [ ] Agent Turn 进入通用 RuntimeTask worker；
- [ ] RuntimeTaskEvent 驱动 Agent SSE 断线续读；
- [ ] 通用 Worker / Handler registry；
- [ ] Planner、Executor、Reviewer、Repair 分层；
- [ ] PolicyDecision 与高风险动作确认；
- [ ] 预算、Usage 和 timeout 的执行期强制；
- [ ] 通用 Replan lineage；
- [ ] PostgreSQL 多进程竞争与故障注入基线。

详细设计：

- `docs/task-runtime.md`
- `docs/implementation-log-m4-20260812.md`

**M4 验收状态：** 通用持久化执行内核已经建立，但尚未接管 Agent。完整验收仍要求 Agent 崩溃后从 checkpoint 恢复且不产生重复实体，高风险动作必须经过 Policy 确认。

## M5 · Evaluator 与 Golden Projects

固定三个 Golden Project：

1. 30 秒广告；
2. 90 秒剧情短片；
3. 3 分钟科普视频。

测试层次：

- 确定性 schema / 状态机测试；
- 故障注入；
- Golden Project 场景回归；
- Agent Eval；
- 真实 Provider 合同测试。

**验收：** 端到端成功率、错误写入率、重复产物率和恢复率有可重复基线。

## M6 · 媒体与渲染生产化

- Provider 异步 submit / poll / cancel / download；
- 外部任务恢复与幂等下载；
- 原始 Asset 不可变，缩略图和转码文件作为派生资产；
- Timeline 编译为 RenderGraph；
- 保存可复现 Render Manifest；
- 安全下载、MIME、大小与 URL 校验。

## M7 · 工作台纵向重构

围绕首个 Golden Path 重构：

```text
简报 → 故事 → 剧本 → 镜头 → 分镜 → 素材 → 时间线 → 预览 → 审阅
```

每一步显示输入、输出、质量、依赖、过期状态、成本和下一步。

## 变更纪律

每个里程碑必须同时包含：

- 设计文档或 ADR；
- 数据迁移；
- 正常路径测试；
- 失败和恢复测试；
- 可观察事件；
- 回滚说明；
- 实施日志。

禁止以“接口已存在”或“页面已显示”作为完成标准。完成标准只能是可验证的用户任务与系统不变量。
