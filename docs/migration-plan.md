# Video Studio V2 迁移计划

> 原则：先修可靠性，再建立内核；先完成一条纵向闭环，再扩展领域。  
> 完成标准是可验证的用户任务与系统不变量，而不是接口或页面存在。

## M0 · 可靠性基线

已完成 SSE 持久游标、Last-Event-ID、手动重试清理、Agent 固定 worker、有界准入、结构化流 checkpoint 与最终消息恢复。

待完成：token 级持久流、数据库游标分页、真实浏览器重连测试与通用故障注入。

## M1 · Artifact Definition Registry

已完成 Alembic baseline、旧库 stamp/升级、ArtifactDefinitionRegistry、核心 schema、统一写入校验和定义查询。领域完整性 Evaluator 归入 M5。

## M2 · CommandBus 与 OperationLog

核心 Artifact、Project、Unit、Asset、Proposal、Timeline、Job、Agent mutating tool 和生成结果已收口到 CommandBus / OperationLog，具备业务幂等、失败审计和首批安全补偿。

待完成：复杂删除完整快照恢复、外部已执行任务的明确补偿边界扩展。

## M3 · Dependency、Freshness 与持久化修复

已完成精确 ArtifactVersion / Asset 输入、Provenance、stale/blocked 传播、单点修复、级联预览、RegenerationPlan/Step、多进程 claim、恢复、Retry、Replan、素材输入与工作台闭环。

待完成：部分成功策略、needs_review、已完成 Step compensation、外部 Provider 强制取消、大图压力、Asset 生产图与更多领域链。

## M4 · Durable Task Runtime 与 Agent 2.0

### 已完成

- [x] `0010` RuntimePlan / Task / Attempt / Event；
- [x] DAG、claim、lease、heartbeat、checkpoint、timeout、retry、Cancel、recovery；
- [x] Agent Turn 原子提交、startup 恢复、SSE 与 logical tool exactly-once；
- [x] `0011` admission slot 与 semantic event dedupe；
- [x] `0012` PolicyDecision、审批暂停恢复、Budget Ledger；
- [x] token、tool call 与 wall-clock 硬预算；
- [x] 项目审批中心与活动 Turn 刷新恢复；
- [x] `0013` 审批 TTL、历史回填和 CAS 回收；
- [x] `0014` 模型价格、不可变 Provider CostEntry 与默认 Agent 成本预算；
- [x] LLM 价格快照、usage 计量、CostEntry exactly-once；
- [x] 成本请求前门限与请求后真实费用保留；
- [x] 模型价格配置、Turn 成本摘要、未定价告警与费用明细。

### 下一步

- [ ] 为未定价 Provider 提供严格项目策略；
- [ ] 外部 Provider idempotency / 异步 request ledger / 账单对账；
- [ ] 图片、视频、TTS、渲染与存储成本；
- [ ] 角色权限、多人审批与双人复核；
- [ ] Planner、Executor、Reviewer、Repair 分层；
- [ ] 通用 RuntimePlan Replan 与 Task compensation；
- [ ] token 级持久化流；
- [ ] PostgreSQL 多进程、网络分区和规模化故障注入；
- [ ] 稳定后评估 RegenerationPlan 适配，避免双写。

详细设计：

- `docs/task-runtime.md`
- `docs/runtime-governance.md`
- `docs/runtime-cost-metering.md`
- `docs/implementation-log-m4-20260812.md`

**M4 验收状态：** 通用执行、Agent exactly-once、准入、持久事件、审批与 TTL、token/tool/wall/cost 预算及首个 LLM 成本计量闭环已经成立。完整 Agent 2.0 仍需角色分层、质量评估和外部 Provider 对账。

## M5 · Evaluator 与 Golden Projects

建立 30 秒广告、90 秒剧情短片、3 分钟科普视频三个 Golden Project，覆盖 schema/状态机、故障注入、场景回归、Agent Eval 与真实 Provider 合同。

## M6 · 媒体与渲染生产化

Provider 异步 submit/poll/cancel/download、外部任务恢复、不可变原始 Asset、派生转码、RenderGraph、Render Manifest、安全下载和媒体成本计量。

## M7 · 工作台纵向重构

```text
简报 → 故事 → 剧本 → 镜头 → 分镜 → 素材 → 时间线 → 预览 → 审阅
```

每一步显示输入、输出、质量、依赖、过期、成本和下一步。

## 变更纪律

每个里程碑必须包含设计文档、数据迁移、正常路径、失败恢复、可观察事件、回滚说明和实施日志。
