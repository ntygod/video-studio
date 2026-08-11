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

- [x] 通过 Alembic 新增版本级 `ArtifactDependency`、`ArtifactProvenance` 和 `ArtifactFreshness`。
- [x] 派生产物记录精确输入 ArtifactVersion，而不是模糊的 Artifact 当前状态。
- [x] LLM 生成结果记录 Provider、Model、Prompt version、参数、seed、Attempt 和 Operation。
- [x] 时间线编译记录实际采用的 edit plan 版本，并在 provenance 参数中记录所用 Asset ID。
- [x] 上游 Artifact 追加新版本后，当前下游递归传播为 `stale`；无关 Artifact 不受影响。
- [x] 暴露版本 provenance、Artifact freshness、dependencies 和 impact API。
- [x] 增加项目级 `/api/projects/{id}/artifact-freshness` 聚合接口，默认只返回需要处理的内容。
- [x] 工作台顶栏、Artifact 面板和结构树显示 `stale / blocked / needs_review`，结构树提供“需处理”筛选。
- [x] 工作台可展开查看后续影响，并深链到目标 Artifact 的版本页。
- [x] 对有完整可重放来源的 `stale` LLM Artifact 提供选择性重新生成：刷新精确输入、保持 Artifact 身份、只追加版本。
- [x] 重新生成使用目标版本乐观锁与确定性 Job 幂等键；重复请求复用同一 Job，执行恢复不会重复追加版本。

### 下一步

- [ ] 建立一等的 `Asset → ArtifactVersion` 依赖边，以及 Asset 删除后的 `blocked` 递归传播。
- [ ] 为缺失素材提供替换、解除阻塞和重新编译的显式操作。
- [ ] 定义 `needs_review` 的自动转换条件和人工确认流程。
- [ ] 支持用户选择多个受影响产物并执行批量 / 级联重新生成。
- [ ] 为故事结构 → 剧本 → 镜头方案 → 分镜等更多生产链自动登记依赖。
- [ ] 增加依赖环检测。
- [ ] 增加图规模限制、数据库级游标遍历和大型项目性能基线。
- [ ] 在项目库卡片显示项目级状态摘要。

详细设计与现有限制见 `docs/m3-freshness-and-regeneration.md`。

**M3 验收状态：** Artifact 版本依赖、`stale` 传播、工作台解释与单个 LLM Artifact 修复闭环已经成立；完整验收仍要求 Asset 阻塞传播、更多生产链依赖、批量修复与图安全边界。

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
