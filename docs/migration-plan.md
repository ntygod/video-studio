# Video Studio V2 迁移计划

> 原则：先修可靠性，再建立内核；先完成一条纵向闭环，再扩展领域。  
> 执行方式：每个里程碑独立分支、独立验收、独立回滚。

## M0 · 可靠性基线

目标：先让现有任务系统的状态、事件和重试行为可信。

### M0.1 任务事件流

- [x] 任务 SSE 从 `job_events` 表增量读取，而不是从不含 events 的任务列表对象读取。
- [x] 使用有界游标查询，避免每个任务一次事件查询。
- [x] 增加持久化事件游标测试。
- [x] 为 job.event 增加 SSE id / Last-Event-ID 续传，并在前端按持久化事件 id 去重。
- [ ] 增加真实浏览器 EventSource 断线/重连集成测试。
- [ ] 为事件积压增加分页续读与监控指标。

### M0.2 手动重试状态机

- [x] 失败或取消任务重试时清理 `cancel_requested`。
- [x] 清理 lease、worker、旧结果和旧错误。
- [x] attempt 归零，获得新的自动重试预算。
- [x] 保留历史事件并追加 retry 审计事件。
- [ ] 统一 worker 终态清理逻辑。

### M0.3 后续可靠性缺陷

- [x] 修复 Agent 新建 Artifact 后无法可靠回合撤销的问题：按版本数量、来源、状态与引用关系判断。
- [x] Agent 回合移入固定 worker + 有界排队执行池，过载返回可解释的 429。
- [ ] 持久化流式输出 checkpoint，补齐断线续传。
- [ ] 把 Python 内存分页改为数据库游标分页。
- [ ] 建立故障注入测试基线。

**M0 验收：** 已取消任务可成功重试；任务事件能够实时到达前端；现有测试全绿；无数据模型破坏性变更。

## M1 · Artifact Definition Registry 与数据库迁移

- [x] 引入 Alembic baseline，停止以删库作为升级方案。
- [x] 空数据库执行 baseline；现有 pre-Alembic 数据库保留数据并自动 stamp。
- [x] 建立 `ArtifactDefinitionRegistry` 和显式 schema migration handler 机制。
- [x] 首批注册 brief、story_outline/story_graph、screenplay、shot_plan、timeline。
- [x] 同步注册当前项目必需的 project_bible。
- [x] 已知类型所有写入统一经过 schema 校验和规范化。
- [x] schema 校验失败返回结构化 422，后台任务则进入可观察失败状态。
- [x] 未知类型继续开放保存，不自动进入正式生产链。
- [x] 暴露 `/api/artifact-definitions`，供前端和工具读取版本化 schema。
- [ ] 为五种核心类型补充领域级完整性 Evaluator；它属于 M5，不混入结构校验。

**M1 验收：** 核心 Artifact 有版本化 schema；非法载荷无法落库；旧数据库无需删除即可采用 Alembic；开放类型仍兼容。

## M2 · CommandBus、OperationLog 与可靠补偿

### 已完成

- [x] 新增 `operation_logs` 持久化表与 Alembic 迁移。
- [x] 建立带业务幂等作用域、前置条件、风险等级、影响实体和失败审计的 CommandBus。
- [x] Artifact 创建、追加版本、恢复、批准、锁定进入 CommandBus。
- [x] 提案创建、接受和拒绝进入同一操作审计链。
- [x] 项目创建/编辑、批量建单元和单元编辑进入 CommandBus。
- [x] JSON Asset 创建、上传、作用域编辑和删除进入 CommandBus。
- [x] 项目删除和单元子树删除采用媒体隔离与事务失败补偿。
- [x] 时间线编译、渲染任务创建、单次/批量生成和批量配音任务创建进入 CommandBus。
- [x] Agent 现有 mutating tools 通过 Command API，并按 turn / step 幂等。
- [x] LLM、Provider 媒体、TTS、渲染和批量配音输出采用 Job / 槽位级幂等持久化。
- [x] 应用启动时把遗留 running Operation 标记为 interrupted/failed，并清理或恢复可识别的媒体中断状态。
- [x] 暴露项目 OperationLog 查询和安全补偿 API。
- [x] 实现首批安全 inverse operation：Artifact、项目/单元编辑、批量建单元、素材作用域、待处理提案与排队任务。

### 保留边界

- [ ] 项目、单元子树和媒体文件删除暂不提供完整关系快照的一键恢复；隔离副本用于崩溃恢复和审计。
- [ ] 已开始执行或已完成的外部生成任务不做“复活式撤销”。
- [ ] 后续新增 mutating tool 必须继续只调用 Command / Query API，并同时提供幂等、失败和审计测试。

**M2 验收状态：** 核心 HTTP、Agent、Job 和媒体写入路径已收口；安全可逆操作具备确定性补偿，跨资源删除具备崩溃恢复边界。

## M3 · Dependency、Provenance 与 Freshness

### 已完成

- [x] 通过 Alembic 新增版本级 `ArtifactDependency`、`ArtifactProvenance`、`ArtifactFreshness` 和 `AssetDependency`。
- [x] 派生产物记录精确 ArtifactVersion 与 Asset 输入；删除 Asset 后保留可解释 tombstone。
- [x] LLM 生成结果记录 Provider、Model、Prompt version、参数、seed、Attempt 和 Operation。
- [x] Timeline 编译登记实际 edit plan 版本和 clip Asset；缺失素材可通过替换映射追加修复版本。
- [x] 上游 Artifact 前进后当前下游递归进入 `stale`；Asset / 单元删除后外部下游递归进入 `blocked`。
- [x] 图登记拒绝自依赖、直接 / 间接环、跨项目输入以及超过安全上限的边。
- [x] 暴露 provenance、freshness、Artifact / Asset dependencies、dependents 和 impact API。
- [x] 项目级 Freshness 默认只返回需要处理的内容；工作台顶栏、Artifact 面板和结构树共享状态模型。
- [x] 工作台可解释原因、查看影响和深链版本；stale / blocked 内容不能直接采用或锁定。
- [x] 对完整可重放来源的 stale LLM Artifact 提供选择性重新生成，保持 Artifact 身份并只追加版本。
- [x] 单点重新生成使用目标版本乐观锁和确定性 Job 幂等键；执行恢复不会重复追加版本。
- [x] Agent `write_artifact` 从工具参数、Turn refs 和 pinned refs 冻结精确输入并登记依赖 / Provenance。
- [x] Agent 媒体任务冻结精确输入到 Job，并在生成 Asset metadata 中保留审计引用。
- [x] 提供只读级联预览：沿当前下游扩展、拓扑排序、冻结 expected version、分类动作与 blocker。

### 下一步

- [ ] 建立持久化 RegenerationPlan / Step，并由可恢复协调器按拓扑释放步骤。
- [ ] 定义级联执行的部分失败、取消、重新规划和用户替换输入审计。
- [ ] 定义 `needs_review` 的自动转换条件和人工确认流程。
- [ ] 为故事结构 → 剧本 → 镜头方案 → 分镜等更多生产链自动登记依赖。
- [ ] 将生成 Asset 建模为可传播 Freshness 的生产节点，而不只保存 generation metadata。
- [ ] 增加 500 节点预览和大型项目的数据库遍历性能基线。
- [ ] 在工作台提供批量选择、素材替换输入和项目库状态摘要。

详细设计：

- `docs/m3-freshness-and-regeneration.md`
- `docs/agent-explicit-production-inputs.md`
- `docs/regeneration-cascade-preview.md`
- `docs/implementation-log-m3-20260812.md`

**M3 验收状态：** 精确输入、Artifact / Asset 图、stale / blocked 传播、单点修复、Agent 输入登记和级联只读预览已经成立；完整级联执行仍依赖持久化计划与可恢复协调器。

## M4 · Durable Task Runtime 与 Agent 2.0

- Plan / Task / TaskAttempt 持久化。
- Agent 回合进入统一 worker。
- Planner、Executor、Reviewer、Repair 分层。
- PolicyDecision、预算、timeout、checkpoint。
- 所有副作用具有 idempotency key。

**验收：** 执行中杀进程后可恢复；同一任务不产生重复实体；高风险动作不会绕过确认。

## M5 · Evaluator 与 Golden Projects

建立三个固定项目：

1. 30 秒广告；
2. 90 秒剧情短片；
3. 3 分钟科普视频。

测试层次：

- 确定性 schema/状态机测试；
- 故障注入；
- Golden Project 场景回归；
- Agent Eval；
- 真实 Provider 合同测试。

**验收：** 端到端成功率、错误写入率、重复产物率和恢复率均有可重复基线。

## M6 · 媒体与渲染生产化

- Provider 异步 submit/poll/cancel/download。
- 外部任务恢复和幂等下载。
- 原始 Asset 不可变，缩略图和转码文件作为派生资产。
- Timeline 编译为 RenderGraph。
- 保存可复现 Render Manifest。
- 安全下载、MIME、大小和 URL 校验。

## M7 · 工作台纵向重构

围绕首个 Golden Path 重构，不同时重做所有页面：

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

禁止以“接口已存在”“页面已显示”作为完成标准。完成标准只能是可验证的用户任务和系统不变量。
