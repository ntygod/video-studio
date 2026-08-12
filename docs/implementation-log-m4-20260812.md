# M4 实施记录 · 2026-08-12

> 分支：`refactor/kernel-v2-foundation`。  
> 当前阶段：M4.1 至 M4.5 首个 Agent 生产治理闭环。

## 1. M4.1 通用运行时

Alembic `20260812_0010` 新增 RuntimePlan、RuntimeTask、RuntimeTaskAttempt 与 RuntimeTaskEvent。

完成 DAG 验证、前驱释放、数据库 claim、lease、heartbeat、checkpoint、Attempt history、timeout、retry backoff、Cancel、事件续读和并发幂等 Plan 创建。

`TaskRuntimeEngine` 提供固定 worker、kind 作用域、Handler registry、自动 heartbeat / reaper 和未知任务 fail-closed。

## 2. M4.2 Agent Turn

Turn 创建原子提交 user message、AgentTurn、Plan、Task 和 queued 事件。startup 无浏览器参与恢复。

Agent tool-loop checkpoint 冻结 Provider / Model、messages、phase、round、tool calls、tool index、Usage 和 final message。logical tool call 和 AgentStep 跨 Attempt 稳定，mutating tool 继续使用 CommandBus 幂等键。

RuntimeTaskEvent 驱动结构化 SSE；live token 不推进持久游标；终态事实提交后缺失事件可自动补齐。

## 3. M4.3 准入与事件身份

Alembic `20260812_0011` 新增：

- runtime admission bucket；
- Plan slot reservation；
- semantic event dedupe。

Agent 默认容量 10。容量满返回 429，Turn 创建事务完整回滚。Plan 终态释放 slot。

结构化 Agent 事件按稳定语义 key 去重，浏览器持久游标只向前推进。

## 4. M4.4 PolicyDecision 与预算

Alembic `20260812_0012` 新增 PolicyDecision、Budget Ledger、Task Usage 水位和 exactly-once Consumption。

高风险工具在副作用之前请求确认。Task 进入 waiting approval，Attempt suspended，checkpoint 持久化并释放 worker。批准或拒绝后新 Attempt 从原 checkpoint 恢复。

默认 Agent 预算为 120k prompt、60k completion、160k total、12 次工具调用和 900 秒。预算在 claim、heartbeat / checkpoint 与工具授权边界执行。

## 5. M4.5 审批工作台、刷新恢复与 TTL

工作台新增项目级审批中心：

- 顶栏显示 pending 数量；
- joined query 返回 Decision 与 Plan 摘要；
- 任意页面可批准或拒绝；
- mutation 刷新项目和 Turn 缓存并唤醒 worker。

AgentPanel 使用持久化 RuntimePlan 恢复当前 Conversation 的活动 Turn。页面刷新不再丢失 pending 审批入口。

Alembic `20260812_0013` 为 Decision 增加 `expires_at` 与 pending-expiry 索引。默认 TTL 为 24 小时，可由冻结 Plan Policy 覆盖，范围 1 秒至 7 天。

过期回收接入 startup / periodic recovery：

```text
pending + expires_at <= now
→ expired
→ waiting Task queued
→ 同一 checkpoint 恢复
```

用户审批与 reaper 使用互斥 CAS。截止时间后的 HTTP 审批先提交 expired 事实，再在事务外返回 409，避免异常回滚过期状态。

## 6. 自动验收

覆盖：

- DAG、claim、lease、timeout、retry、Cancel；
- startup recovery；
- logical tool exactly-once；
- Agent checkpoint 和冻结 Model；
- SSE 重放与事件去重；
- admission 并发与 429 原子回滚；
- Policy pending / approve / deny；
- 高风险动作批准前零副作用，批准后执行一次；
- stale claim 授权拒绝；
- token / tool / wall budget；
- Usage 重放不重复累计；
- 项目级审批查询；
- 刷新后的活动 Turn 选择；
- TTL 到期只恢复一次；
- 截止时间后审批不能覆盖 expired；
- fresh / legacy migration；
- 后端、前端测试、lint、设计检查与生产构建。

## 7. 当前边界

- Planner / Executor / Reviewer / Repair 尚未分层；
- Provider 价格表与真实 cost 换算未接入；
- 尚无角色权限、多人审批或双人复核；
- 通用 Replan 与 compensation 未实现；
- token 级输出不持久；
- PostgreSQL 多进程与系统性故障注入基线仍待建立；
- RegenerationPlan 暂不迁入，避免双写。

## 8. 回滚

所有 Runtime、Decision、Budget、Admission、Event、AgentTurn、Operation 和业务实体记录均为审计事实。回滚应用代码时保留表和历史；不要通过删除 Plan、Decision 或 ArtifactVersion 伪装动作从未发生。
