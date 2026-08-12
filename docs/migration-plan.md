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
- [x] Agent 回合进入固定 worker 与有界队列；该内存执行器已在 M4 被持久化 Runtime 取代；
- [x] Agent 结构化流与最终消息具备持久化 checkpoint / 续读；
- [ ] token 级持久化流输出；
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
- [x] Agent mutating tools 只调用 Command API，并按稳定 logical tool call 幂等；
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
- [ ] 更多生产链自动登记；
- [ ] 项目库卡片显示项目状态与 active Plan 摘要。

详细设计见 M3 系列文档。

**M3 验收状态：** 精确输入、图传播、单点修复、级联预览、多进程执行、崩溃恢复、Retry、Replan 与工作台闭环已经成立。

## M4 · Durable Task Runtime 与 Agent 2.0

### 已完成

- [x] `0010`：RuntimePlan / Task / Attempt / Event；
- [x] DAG、claim、lease、heartbeat、checkpoint、timeout、retry、Cancel 与 recovery；
- [x] Plan 事件序号、并发幂等创建和 Handler registry；
- [x] Agent Turn 与 Plan / Task 原子提交；
- [x] 冻结 Provider / Model 和 tool-loop checkpoint；
- [x] logical tool call、AgentStep 与 Command exactly-once；
- [x] startup 无浏览器恢复；
- [x] RuntimeTaskEvent SSE 续读、live token 隔离和终态事件修复；
- [x] `0011`：数据库 admission slot 与语义事件去重；
- [x] 容量满 429 的 Turn 创建原子回滚；
- [x] `0012`：持久化 PolicyDecision、用户确认和 Budget Ledger；
- [x] 高风险动作在副作用前 suspend，批准 / 拒绝后从 checkpoint 恢复；
- [x] token、tool call 与 wall-clock 执行期硬预算；
- [x] 项目级审批中心和单 Turn 审批卡；
- [x] 页面刷新后自动恢复 Conversation 的活动 Turn；
- [x] `0013`：审批期限、历史 pending 回填和周期过期回收；
- [x] 用户审批与到期 reaper 的数据库 CAS；
- [x] fresh / legacy 迁移、并发、故障窗口、前后端和生产构建测试。

### 下一步

- [ ] Planner、Executor、Reviewer、Repair 分层；
- [ ] Provider 价格表与真实 cost 计量；
- [ ] 角色权限、多人审批与双人复核；
- [ ] 通用 RuntimePlan Replan lineage；
- [ ] 通用 Task compensation；
- [ ] token 级持久化流输出；
- [ ] PostgreSQL 多进程、网络分区和大规模故障注入基线；
- [ ] 稳定后评估 RegenerationPlan 适配，避免双写。

详细设计：

- `docs/task-runtime.md`
- `docs/runtime-governance.md`
- `docs/implementation-log-m4-20260812.md`

**M4 验收状态：** 通用执行内核、Agent exactly-once、准入、持久事件、审批发现与期限回收、PolicyDecision 和硬预算首个生产闭环已经成立。完整 Agent 2.0 仍需角色分层、真实成本和质量评估。

## M5 · Evaluator 与 Golden Projects

固定三个 Golden Project：30 秒广告、90 秒剧情短片和 3 分钟科普视频。测试包括 schema / 状态机、故障注入、场景回归、Agent Eval 与真实 Provider 合同。

## M6 · 媒体与渲染生产化

- Provider 异步 submit / poll / cancel / download；
- 外部任务恢复与幂等下载；
- 原始 Asset 不可变，派生缩略图与转码；
- Timeline → RenderGraph；
- 可复现 Render Manifest；
- 安全下载、MIME、大小与 URL 校验。

## M7 · 工作台纵向重构

```text
简报 → 故事 → 剧本 → 镜头 → 分镜 → 素材 → 时间线 → 预览 → 审阅
```

每一步显示输入、输出、质量、依赖、过期、成本和下一步。

## 变更纪律

每个里程碑必须包含设计文档、迁移、正常路径、失败恢复、可观察事件、回滚说明和实施日志。完成标准只能是可验证的用户任务与系统不变量。
