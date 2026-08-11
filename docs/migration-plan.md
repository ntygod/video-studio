# Video Studio V2 迁移计划

> 原则：先修可靠性，再建立内核；先完成一条纵向闭环，再扩展领域。  
> 执行方式：每个里程碑独立分支、独立验收、独立回滚。

## M0 · 可靠性基线

目标：先让现有任务系统的状态、事件和重试行为可信。

### M0.1 任务事件流

- [x] 任务 SSE 从 `job_events` 表增量读取，而不是从不含 events 的任务列表对象读取。
- [x] 使用有界游标查询，避免每个任务一次事件查询。
- [x] 增加持久化事件游标测试。
- [ ] 增加真实 EventSource 断线/重连集成测试。
- [ ] 为事件积压增加分页续读与监控指标。

### M0.2 手动重试状态机

- [x] 失败或取消任务重试时清理 `cancel_requested`。
- [x] 清理 lease、worker、旧结果和旧错误。
- [x] attempt 归零，获得新的自动重试预算。
- [x] 保留历史事件并追加 retry 审计事件。
- [ ] 统一 worker 终态清理逻辑。

### M0.3 后续可靠性缺陷

- [ ] 修复 Agent 新建 Artifact 后无法可靠回合撤销的问题。
- [ ] Agent 回合移入有界执行池，停止每回合创建裸线程。
- [ ] 持久化流式输出 checkpoint，补齐断线续传。
- [ ] 把 Python 内存分页改为数据库游标分页。
- [ ] 建立故障注入测试基线。

**M0 验收：** 已取消任务可成功重试；任务事件能够实时到达前端；现有测试全绿；无数据模型破坏性变更。

## M1 · Artifact Definition Registry 与数据库迁移

- 引入 Alembic 版本基线，停止删库升级。
- 建立 `ArtifactDefinitionRegistry`。
- 首批注册 brief、story_outline、screenplay、shot_plan、timeline。
- 已知类型写入必须通过 schema 校验。
- schema 升级通过显式 migration handler。
- 未知类型降级为 custom，不自动进入生产链。

**验收：** 五种核心 Artifact 有版本化 schema、验证错误可理解、旧数据库可以原地升级。

## M2 · CommandBus、OperationLog 与可靠撤销

- 所有跨实体写入收口到 CommandBus。
- 引入语义 Operation 和 precondition。
- 写入 OperationLog、affected entities 和 inverse operation。
- Agent 工具只能调用 Command / Query API。
- 提案采纳、用户编辑和 Agent 写入共享同一条写路径。

**验收：** 新增、修改、移动、删除均可审计；可逆操作可确定性撤销；不再依靠 revision/时间戳猜测。

## M3 · Dependency、Provenance 与 Freshness

- 新增 ArtifactDependency、ArtifactProvenance、ArtifactFreshness。
- 记录派生产物所使用的精确输入版本。
- 上游新版本触发下游 stale 传播。
- UI 显示影响范围和选择性重新生成入口。
- 时间线和渲染结果纳入依赖图。

**验收：** 修改剧本后，相关 shot plan、storyboard、timeline 和 render 被准确标记；无关内容不受影响。

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
