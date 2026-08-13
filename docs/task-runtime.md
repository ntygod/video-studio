# M4 通用耐久任务运行时与 Agent Turn

> 状态：通用执行内核、Agent Turn、准入、事件、Policy、审批、硬预算与 LLM 成本计量闭环已实现。  
> 日期：2026-08-13。  
> Alembic head：`20260812_0014`。

## 1. 架构

```text
RuntimePlan
  └── RuntimeTask DAG
        └── RuntimeTaskAttempt
              └── RuntimeTaskEvent
```

控制平面：

```text
Admission Reservation
PolicyDecision
Budget Ledger / Task Usage / Consumption
Provider Cost Entry
Semantic Event Dedupe
```

M4 将 claim、lease、checkpoint、Attempt、事件、策略、审批与预算抽成领域无关 Runtime，并让 Agent Turn 成为首个生产消费者。

## 2. 迁移链

```text
0010  RuntimePlan / Task / Attempt / Event
0011  数据库准入 slot 与语义事件去重
0012  PolicyDecision 与 Budget Ledger
0013  审批期限与历史 pending 回填
0014  Model Pricing 与 Runtime Cost Entry
```

## 3. 执行不变量

- Plan Queue 后执行；
- Task 前驱成功后 claim；
- 数据库 CAS 保证唯一 worker；
- 每次 claim 创建不可变 Attempt；
- heartbeat 更新 Task / Attempt / checkpoint / usage；
- claim token 拒绝迟到 worker；
- lease / timeout 恢复创建新 Attempt；
- 未分类异常默认不重试；
- Cancel 原子终止执行；
- Plan 终态由持久化 Task 状态归并。

`TaskRuntimeEngine` 提供固定 worker、Handler registry、heartbeat、reaper 和 fail-closed 未知任务处理。

## 4. Agent Turn 与 exactly-once

Turn 创建事务提交 user message、AgentTurn、`agent.turn` Plan、执行 Task、queued 事件和 admission reservation。

startup 自动恢复。Checkpoint 冻结 Provider、Model、messages、phase、round、tool calls、tool index、价格快照、Usage 与 final message。

logical tool call 由 round、call index、Provider call ID、工具名和规范化参数确定。mutating tool 继续使用：

```text
agent:{turn_id}:{stable_step_id}
```

Command 已提交而 Step/checkpoint 未提交时，恢复读取原 Operation，不重复业务实体。

## 5. 事件、SSE 与准入

结构化事件使用 Plan 单调 seq；SSE 游标为 `{turn_id}:{seq}`。live token 不推进持久游标；final message 修复断线文本。

语义去重覆盖 Step、Entity、Proposal、Message、Done、Approval 与 Budget。

Agent 默认 admission 容量 10。容量满返回 429，并回滚整个 Turn 创建事务。等待审批不占 worker但保留 slot。

## 6. Policy、审批与预算

高风险工具在副作用前进入 `waiting_approval`；Decision 默认 24 小时过期。用户审批与 reaper 通过数据库 CAS 决定唯一终态。

默认预算：

```text
prompt       120,000
completion    60,000
total        160,000
tool calls        12
cost             $10
wall-clock       900s
```

Token 使用绝对水位，工具与 Provider usage 使用稳定唯一 key。重试、heartbeat 和事件重放不会重复消费。

模型价格在 Provider 请求前冻结。真实 usage 生成不可变 CostEntry 并进入 Ledger；改价不影响旧 Turn。详细见：

- `docs/runtime-governance.md`
- `docs/runtime-cost-metering.md`

## 7. 可观察接口

```http
GET /api/projects/{project_id}/runtime-plans
GET /api/runtime-plans/{plan_id}
GET /api/runtime-tasks/{task_id}
GET /api/runtime-plans/{plan_id}/events
GET /api/runtime-plans/{plan_id}/budget
GET /api/runtime-plans/{plan_id}/costs
GET /api/projects/{project_id}/runtime-policy-decisions
GET /api/turns/{turn_id}/policy-decisions
GET /api/turns/{turn_id}/budget
GET /api/turns/{turn_id}/costs
```

外部没有通用 Runtime 写 API；业务写入继续经过应用服务、CommandBus 与领域前置条件。

## 8. 已验证窗口

| 窗口 | 行为 |
| --- | --- |
| Plan 提交后退出 | startup worker claim |
| Command 提交、Step 未完成 | Operation replay |
| Step 完成、tool index 未提交 | 读取原 Step |
| assistant message 提交、事件未写 | 补齐 message / done |
| SSE 断线 | 持久 seq 续读 |
| heartbeat / Attempt 重放 | Usage 水位不重复累计 |
| 等待审批重启 | Decision 与 checkpoint 保留 |
| 两人审批或审批/TTL 竞争 | 一个 CAS 胜出 |
| 价格冻结后改价 | 旧快照继续计价 |
| Provider usage 重放 | 返回原 CostEntry |
| 响应使费用跨预算 | 先记账，再失败关闭 |
| 当前费用已到上限 | 请求前拒绝下一次 Provider 调用 |

## 9. 当前边界

- Planner / Executor / Reviewer / Repair 尚未分层；
- 外部 Provider 请求没有通用 exactly-once 与账单对账；
- 媒体/TTS/渲染/存储成本尚未接入；
- 通用 Replan 与 Task compensation 尚未实现；
- token 级输出不持久；
- PostgreSQL 多实例、网络分区与规模化故障注入仍需建立；
- RegenerationPlan 暂不迁入通用 Runtime，避免双写。

## 10. 回滚

Runtime、Decision、Budget、CostEntry、Admission、Operation 与业务版本都是历史事实。应用回滚不应删表、删版本或重算旧费用。
