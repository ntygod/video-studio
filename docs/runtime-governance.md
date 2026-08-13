# Runtime Policy、审批与预算治理

> 状态：Agent 高风险审批、期限回收、token/tool/wall 与真实 LLM 成本治理闭环已实现。  
> 日期：2026-08-13。  
> Alembic revision：`20260812_0011` 至 `20260812_0014`。

## 1. 控制平面

通用 Runtime 的控制平面由以下持久化事实组成：

```text
Admission Reservation
PolicyDecision
Budget Ledger / Task Usage / Consumption
Provider Cost Entry
Semantic Event Dedupe
```

它们共同回答动作是否允许、是否需要审批、等待多久、消耗多少，以及恢复或并发是否会重复执行与重复计费。

## 2. PolicyDecision

每个逻辑动作最多一条决策：

```text
UNIQUE(plan_id, action_key)
```

状态为：

```text
allowed / pending / approved / denied / expired
```

Decision 保存 Plan、Task、动作、风险、Policy version、上下文、请求者、决定者、原因、备注和 `expires_at`。恢复时工具名或风险发生漂移会冲突失败。

默认 Agent Policy：

```json
{
  "version": "agent-runtime-policy@1",
  "confirmation_risk_levels": ["high"],
  "denied_actions": [],
  "allowed_actions": [],
  "approval_ttl_seconds": 86400
}
```

读取与提案为 low，`write_artifact / create_units` 为 medium，`generate_media` 与未知 mutating tool 为 high。

## 3. 审批状态机

高风险动作在副作用前：

1. 创建或读取稳定 Decision；
2. 保存 checkpoint 与 usage；
3. Task 进入 `waiting_approval`；
4. Attempt 进入 `suspended`；
5. 释放 claim 与 worker。

批准或拒绝后：

```text
waiting_approval → queued → 新 Attempt
```

批准后动作执行一次；拒绝或过期后读取同一 Decision，动作不执行。

审批与 TTL reaper 使用互斥数据库 CAS。截止时间后的 HTTP 请求先提交 expired 与 Task 恢复，再在事务外返回 409，避免异常回滚过期事实。

## 4. Admission 与事件身份

`runtime_admission_reservations` 为活动 Plan 分配数据库 slot。Agent 默认容量 10；容量满返回 429，用户消息、Turn、Plan 与 Task 整体回滚。

等待审批不占 worker但仍占 slot。Plan 终态释放 slot。

`runtime_event_dedupes` 为 Step、Entity、Message、Done、Approval 和 Budget 事件保存语义身份。重放返回原 Event ID 与 seq。

## 5. Budget Ledger

预算数据包括：

- `runtime_budget_ledgers`：Plan 聚合；
- `runtime_budget_task_usage`：Task 绝对水位；
- `runtime_budget_consumptions`：工具调用等 exactly-once 消耗；
- `runtime_cost_entries`：不可变 Provider 调用费用。

支持：

```text
max_prompt_tokens
max_completion_tokens
max_total_tokens
max_tool_calls
max_cost_microunits / max_cost_usd
max_wall_seconds
```

默认 Agent：120k prompt、60k completion、160k total、12 tool calls、10 USD、900 秒。

Token heartbeat 使用绝对水位，只累计正增量。工具调用以稳定 consumption key 计一次。Provider usage 以稳定 usage key 计一次。

## 6. Provider 费用

模型价格使用整数微美元持久化，并在第一个真实请求前冻结进 Agent checkpoint。CostEntry 保存 Provider、Model、价格快照、usage、分项和金额；后续改价不重写历史。

到达成本上限时，下一次 Provider 调用在发出请求前失败。如果一次响应让成本跨过上限，则真实费用先提交，随后 Turn 失败关闭。

缺少模型价格或 token usage 的调用仍保留审计，并明确计入 `unpriced_calls`。详细契约见 `docs/runtime-cost-metering.md`。

## 7. 工作台

- Agent 当前 Turn 显示审批卡；
- 项目顶栏提供待审批中心；
- 页面刷新后恢复 Conversation 的活动 Turn；
- 模型设置支持 LLM 输入、输出、缓存与单次请求价格；
- Agent Turn 显示 USD 成本、token、Provider 调用、预算上限与费用明细；
- 未完整计价与预算超限会明确告警。

## 8. API

```http
GET  /api/turns/{turn_id}/policy-decisions
GET  /api/projects/{project_id}/runtime-policy-decisions
GET  /api/runtime-policy-decisions/{decision_id}
POST /api/runtime-policy-decisions/{decision_id}/approve
POST /api/runtime-policy-decisions/{decision_id}/deny
GET  /api/runtime-plans/{plan_id}/budget
GET  /api/runtime-plans/{plan_id}/costs
GET  /api/turns/{turn_id}/budget
GET  /api/turns/{turn_id}/costs
```

外部调用者不能直接改 Plan、Task、Attempt、Ledger 或 CostEntry。

## 9. 已验证不变量

覆盖 Decision 唯一性、批准前零副作用、批准后单次执行、拒绝/过期、旧 claim 拒绝、Usage 水位、tool exactly-once、wall budget、成本快照、CostEntry exactly-once、成本前置拒绝、跨预算后费用保留、项目审批查询、活动 Turn 恢复、TTL CAS 与迁移。

## 10. 当前边界

- 尚无组织角色、多人或双人复核；
- 未定价 Provider 不具备严格金额上限；
- 外部 Provider 请求本身尚无通用 idempotency / 账单对账；
- 媒体、TTS、渲染和存储成本尚未计量；
- Planner / Executor / Reviewer / Repair 尚未分层；
- 通用 Replan、compensation、token 持久流和 PostgreSQL 故障基线尚未完成。

## 11. 回滚

Decision、Ledger、CostEntry、Admission、Event、Operation 与业务版本均为审计事实。应用回滚不得删除、重算或把 pending / expired 动作视为已执行。
