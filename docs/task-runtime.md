# M4 通用耐久任务运行时与 Agent Turn

> 状态：通用执行内核、Agent Turn、准入、事件去重、PolicyDecision、审批工作台与硬预算闭环已实现。  
> 日期：2026-08-12。  
> Alembic head：`20260812_0013`。

## 1. 架构

```text
RuntimePlan
  └── RuntimeTask DAG
        └── RuntimeTaskAttempt
              └── RuntimeTaskEvent
```

控制平面包括：

```text
Admission Reservation
PolicyDecision
Budget Ledger / Task Usage / Consumption
Semantic Event Dedupe
```

M3 RegenerationPlan 证明领域级恢复可行；M4 将 claim、lease、checkpoint、Attempt、事件、准入、策略和预算抽成通用 Runtime，并让 Agent Turn 成为第一个生产消费者。

## 2. 迁移链

```text
20260812_0010  RuntimePlan / Task / Attempt / Event
20260812_0011  数据库准入 slot 与语义事件去重
20260812_0012  PolicyDecision 与 Budget Ledger
20260812_0013  审批期限、索引与历史 pending 回填
```

fresh 与 pre-Alembic 数据库均通过升级测试。

## 3. 执行不变量

- Plan Queue 后才能执行；
- Task 仅在全部前驱成功后 claim；
- 数据库 CAS 保证唯一 worker；
- 每次 claim 创建不可变 Attempt；
- heartbeat 同时更新 Task 与 Attempt；
- claim token 拒绝旧 worker 迟到提交；
- lease / timeout 恢复创建新 Attempt；
- 普通未知异常默认不重试；
- Cancel 原子终止 Plan、Task 和 running Attempt；
- Plan 终态由全部 Task 持久化状态归并。

`TaskRuntimeEngine` 提供固定 worker、Handler registry、自动 heartbeat、周期 reaper 和 fail-closed 未知任务处理。

## 4. Agent Turn

创建 Turn 时，同一事务提交：

1. user message；
2. AgentTurn；
3. `agent.turn` RuntimePlan；
4. `agent.turn.execute` RuntimeTask；
5. queued 事件和 admission reservation。

应用 startup 主动恢复 queued / interrupted Turn，不依赖浏览器访问。Agent checkpoint 冻结 Provider、Model、messages、phase、round、tool calls、tool index、Usage、final text 和 assistant message ID。

每个 logical tool call 根据 round、call index、Provider call ID、工具名和规范化参数得到稳定身份。mutating tool 通过 CommandBus，幂等键为：

```text
agent:{turn_id}:{stable_step_id}
```

Command 已提交、Step 或 checkpoint 尚未提交时，恢复只读取原 Operation 结果，不重复实体。

## 5. 事件与 SSE

结构化事件持久化到 RuntimeTaskEvent，并使用 Plan 内单调 seq。SSE 以：

```text
{turn_id}:{seq}
```

续读。实时 token 标记 `durable=false`，不会推进持久化游标；最终 message 替换可能缺失的 token 文本。

语义事件去重覆盖 Step、Entity、Proposal、Message、Done、Approval required/resolved 和 Budget exceeded。重放返回原 Event ID 与 seq。

## 6. 数据库准入

`agent.turn` 默认容量为 10。Plan Queue 与 slot reservation 在同一事务中；容量满返回 429，用户消息、Turn、Plan 和 Task 全部回滚。

Plan 终态释放 slot。等待审批的 Plan 不占 worker，但仍占 slot，防止无限 pending。

## 7. Policy 与预算

高风险 Agent 工具默认需要确认。Task 在副作用前进入 `waiting_approval`，Attempt suspended，checkpoint 已提交，claim 已释放。

工作台支持单 Turn 审批卡和项目级待审批中心；刷新后会恢复 Conversation 对应的活动 Turn。

Decision 默认 24 小时过期。审批和过期以互斥 CAS 决定胜者；reaper 回收后从同一 checkpoint 恢复，动作不会执行。详细契约见 `docs/runtime-governance.md`。

默认预算：

```text
prompt       120,000
completion    60,000
total        160,000
tool calls        12
wall-clock       900s
```

Usage 使用 Task 绝对水位计算 Plan 增量，heartbeat 和 Attempt 重放不重复计费。

## 8. 可观察接口

```http
GET /api/projects/{project_id}/runtime-plans
GET /api/runtime-plans/{plan_id}
GET /api/runtime-tasks/{task_id}
GET /api/runtime-plans/{plan_id}/events
GET /api/runtime-plans/{plan_id}/budget
GET /api/projects/{project_id}/runtime-policy-decisions
GET /api/turns/{turn_id}/policy-decisions
```

外部没有通用 Runtime 写 API；业务写入继续经过应用服务、CommandBus 与领域前置条件。

## 9. 已验证窗口

| 窗口 | 恢复行为 |
| --- | --- |
| Plan 已提交、进程退出 | startup worker claim |
| ToolCall checkpoint 已提交、尚未执行 | 同一 logical call / Step |
| Command 已提交、Step 未完成 | Operation replay |
| Step 完成、tool index 未提交 | 读取原 Step 结果 |
| assistant message 已提交、事件未写 | 补齐缺失 message / done |
| SSE 断线 | 从持久 seq 续读 |
| heartbeat 重放 | Usage 水位不重复累计 |
| 等待审批时重启 | pending Decision 与 checkpoint 保留 |
| 两人同时审批 | 一个 Decision CAS 胜出 |
| 审批期限与用户点击竞争 | 截止时间条件决定唯一终态 |
| 容量满 | 整个 Turn 创建事务回滚 |

## 10. 当前边界

- Planner / Executor / Reviewer / Repair 尚未分层；
- Provider 真实价格和 cost 换算尚未接入；
- 通用 Replan lineage 与 Task compensation 尚未实现；
- token 级输出不持久；
- PostgreSQL 多实例、网络分区与规模化故障注入仍需建立；
- RegenerationPlan 暂不迁入通用 Runtime，避免双写。

## 11. 回滚

Runtime、Decision、Budget、Admission、Operation 和业务版本都是历史事实。应用回滚不应删表或删除版本。兼容版本可忽略新控制字段，但不得把 pending / expired 动作视为已执行。
