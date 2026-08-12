# Runtime Policy、审批与预算治理

> 状态：首个 Agent 高风险动作治理闭环已实现。  
> 日期：2026-08-12。  
> Alembic revision：`20260812_0011` 至 `20260812_0013`。

## 1. 目标

通用 Runtime 不只要保证任务能恢复，还必须回答：

1. 一个动作是否允许执行；
2. 哪些动作需要用户明确确认；
3. 用户离开页面或服务重启后，确认请求是否仍存在；
4. token、工具次数和 wall-clock 是否超过预算；
5. 重试、恢复和并发审批是否会重复消费预算或重复执行副作用；
6. 长期无人处理的审批是否会永久占用运行容量。

当前实现把这些问题收口到数据库中的 PolicyDecision、Budget Ledger、Admission Reservation 和 RuntimeTask 状态，而不是依赖浏览器或单进程内存。

## 2. 数据模型

### 2.1 RuntimePolicyDecision

每个逻辑动作最多一条决策：

```text
UNIQUE(plan_id, action_key)
```

保存：

- Plan、Task 和稳定 action key；
- action type、risk level 与 policy version；
- `allowed / pending / approved / denied / expired`；
- 决策上下文；
- 请求者和决定者；
- 原因、备注与时间戳；
- `expires_at`。

恢复时必须使用同一个 action key。若工具名、风险或动作类型改变，系统冲突失败，不重新解释旧动作。

### 2.2 Budget Ledger

预算由三类记录组成：

- `runtime_budget_ledgers`：Plan 聚合值；
- `runtime_budget_task_usage`：每个 Task 最后一次绝对 Usage 水位；
- `runtime_budget_consumptions`：工具调用等非 token 消耗的 exactly-once 记录。

Task heartbeat 上报绝对 Usage，Ledger 只累计相对上次水位的正增量。Attempt 恢复或 heartbeat 重放不会重复计费。

### 2.3 Admission 与事件去重

`runtime_admission_reservations` 为活动 Plan 占用数据库 slot。等待审批的 Plan 仍占用 slot，防止调用者制造无限 pending 请求。

`runtime_event_dedupes` 保存结构化事件的语义身份。审批 required/resolved、Step、Entity、Message 和 Done 重放时返回原 Event，而不是追加第二条记录。

## 3. 默认 Agent Policy

当前 Agent Plan 创建时冻结：

```json
{
  "version": "agent-runtime-policy@1",
  "confirmation_risk_levels": ["high"],
  "denied_actions": [],
  "allowed_actions": [],
  "approval_ttl_seconds": 86400
}
```

工具风险等级：

| 工具 | 风险 |
| --- | --- |
| 读取、搜索、创建提案 | low |
| `write_artifact`、`create_units` | medium |
| `generate_media` | high |
| 未识别的新 mutating tool | high，保守处理 |

Policy 冻结在 Plan 中。应用默认设置以后改变，不会改写已提交 Plan 的语义。

## 4. 审批状态机

高风险动作到达副作用边界时：

1. 使用 logical tool call 生成稳定 `action_key`；
2. 在持有当前 Task claim 时创建或读取 PolicyDecision；
3. pending 决策写入 `expires_at`；
4. checkpoint 和 Usage 持久化；
5. Task 进入 `waiting_approval`；
6. Attempt 进入 `suspended`；
7. claim 与 lease 释放；
8. worker 立即处理其他任务。

批准或拒绝后：

```text
waiting_approval → queued → 新 Attempt
```

新 Attempt 从原 checkpoint 恢复。批准后动作执行一次；拒绝或过期后读取同一个 Decision，动作不会执行，Agent 工具步骤得到明确失败结果并可继续解释。

审批等待不占 worker，但仍占 Plan admission slot。

## 5. 并发与期限

### 5.1 用户审批与过期回收竞争

批准/拒绝使用数据库条件更新：

```text
status = pending
AND (expires_at IS NULL OR expires_at > now)
```

过期回收使用：

```text
status = pending
AND expires_at <= now
```

只有一个 CAS 可以成功。因此：

- 截止时间前提交的审批可以获胜；
- 截止时间后的审批不能覆盖 expired；
- 两个审批者不能产生两个不同终态；
- reaper 重复扫描不会重复恢复 Task；
- `agent.approval.resolved` 只记录一次。

若 HTTP 请求在截止时间后到达，仓储先提交 expired、重新排队 Task 和审计事件；事务提交后 API 返回 409。不能在同一事务内先写 expired 再抛错，否则 UnitOfWork 会回滚过期事实。

### 5.2 TTL

默认：

```text
24 小时
```

Policy 可设置：

```json
{"approval_ttl_seconds": 3600}
```

运行时限制在 1 秒到 7 天之间。迁移会为历史 Agent Plan 补默认 TTL，并为已有 pending Decision 计算期限。

TaskRuntimeEngine 的 startup recovery 和周期 reaper 都会扫描到期 Decision。到期后 Task 从同一 checkpoint 恢复，无需用户重新打开页面。

## 6. 执行期硬预算

默认 Agent 预算：

```json
{
  "max_prompt_tokens": 120000,
  "max_completion_tokens": 60000,
  "max_total_tokens": 160000,
  "max_tool_calls": 12,
  "max_wall_seconds": 900
}
```

支持维度：

- prompt tokens；
- completion tokens；
- total tokens；
- tool calls；
- cost microunits；
- wall-clock。

检查发生在：

- claim 前；
- heartbeat / checkpoint；
- 工具动作授权和 exactly-once 消耗时。

越界 Usage 会先提交 Ledger 和唯一 `agent.budget.exceeded` 事件，再通过控制信号终止执行。不能通过抛异常让 Usage 一起回滚。

当前 cost ledger 已存在，但真实 Provider 价格表和调用成本换算尚未接入。

## 7. 工作台

### 7.1 当前 Turn

AgentPanel 会查询当前 Conversation 对应的活动 `agent.turn` Plan。页面刷新、面板折叠或重新进入项目后，仍会恢复同一个 Turn、SSE、Step 和审批卡片。

### 7.2 项目级审批中心

工作台顶栏显示项目 pending Decision 数量。抽屉一次 joined query 读取 Decision 与 Plan 摘要，避免逐条查询 Plan。

用户可以在任意页面：

- 查看动作、风险、参数摘要和原因；
- 批准；
- 拒绝；
- 看到请求已被其他用户处理或已经过期。

批准/拒绝会刷新 Turn 与项目审批缓存，并唤醒 Agent RuntimeEngine。

## 8. API

```http
GET  /api/turns/{turn_id}/policy-decisions
GET  /api/projects/{project_id}/runtime-policy-decisions
GET  /api/runtime-policy-decisions/{decision_id}
POST /api/runtime-policy-decisions/{decision_id}/approve
POST /api/runtime-policy-decisions/{decision_id}/deny
GET  /api/runtime-plans/{plan_id}/budget
```

项目列表支持 status、kind 和 limit。写入只允许对 pending Decision 进行终态解析；调用者不能直接改 Plan、Task、Attempt 或 Ledger。

## 9. 已验证不变量

自动测试覆盖：

- pending Decision 唯一身份；
- 高风险动作在批准前不创建 Job 或 Step 副作用；
- 批准后从 checkpoint 恢复并只执行一次；
- 重复批准幂等；
- 拒绝路径；
- 旧 claim 无法授权；
- token Usage 重放不重复累计；
- tool budget exactly-once；
- wall-clock 在 claim 和 heartbeat 边界生效；
- 项目级 pending Decision joined query；
- 页面刷新后的活动 Turn 选择；
- 到期 Decision 只恢复一次；
- 截止时间后用户审批不能覆盖 expired；
- fresh / legacy migration；
- 后端、前端测试、lint、设计检查与生产构建。

## 10. 当前边界

尚未完成：

1. 组织角色、审批权限、多人或双人复核；
2. Provider 价格表与真实 cost 计量；
3. 审批委派、批量审批和 SLA 通知；
4. Planner / Executor / Reviewer / Repair 分层决策；
5. 通用 RuntimePlan Replan 和 compensation；
6. token 级持久化流；
7. PostgreSQL 多实例、网络分区与大规模审批竞争基线。

## 11. 回滚

Decision、Ledger、Consumption、Admission 和 Event 都是执行审计事实。应用回滚不应删除这些表或把 pending 动作直接当作已批准。

若回滚到不识别 `expires_at` 的兼容版本，可保留新增列和索引；后续版本仍能继续回收。数据库 downgrade 会移除期限列，但生产回滚优先保留数据结构。
