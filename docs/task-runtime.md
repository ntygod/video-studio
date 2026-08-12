# M4 通用耐久任务运行时与 Agent Turn

> 状态：通用执行内核与 Agent Turn 首个生产闭环已实现。  
> 日期：2026-08-12。  
> Alembic revision：`20260812_0010`。

## 1. 目标

M3 的 `RegenerationPlan / RegenerationPlanStep` 已经验证数据库租约、拓扑释放、崩溃恢复、Retry 与 Replan，但它仍属于 Artifact 修复领域。M4 把可复用的执行不变量抽成领域无关运行时，并让 Agent Turn 成为第一个生产消费者：

```text
RuntimePlan
  └── RuntimeTask DAG
        └── RuntimeTaskAttempt
              └── RuntimeTaskEvent
```

Agent 不再依赖一次进程内 Future 才能完成。创建 Turn 时，用户消息、AgentTurn、RuntimePlan 和 RuntimeTask 在同一事务中提交；应用启动、读取 Turn 或订阅流均可唤醒持久化执行。

## 2. 通用数据模型

### 2.1 RuntimePlan

Plan 表示一次用户或系统执行意图，保存：

- 项目、`kind`、`subject_type` 与 `subject_id`；
- 可选业务幂等键；
- `draft / queued / running / blocked / succeeded / failed / canceled`；
- 输入、Policy、预算、Usage、结果与错误；
- Plan 内单调事件序号；
- 创建、启动与完成时间。

### 2.2 RuntimeTask

Task 是 DAG 节点，保存：

- Plan 内稳定 `task_key` 与 `task_type`；
- 前驱 Task ID；
- payload、Policy、checkpoint、Usage 与结果；
- attempt 上限、timeout 与 `available_at`；
- cancel 标记；
- 数据库 claim token、owner、lease 与 claim 次数。

### 2.3 RuntimeTaskAttempt

每次成功 claim 都创建一个新 Attempt。Attempt 保存：

- 单调 attempt 编号；
- worker 和 claim token；
- checkpoint 与 Usage；
- 结果、错误和是否可重试；
- heartbeat、lease 与终态时间。

旧 Attempt 不会被新尝试覆盖。迟到 worker 只有旧 token，无法提交新 Attempt 的状态。

### 2.4 RuntimeTaskEvent

事件保存 Plan、Task、Attempt、事件类型、结构化 payload 与 Plan 内单调 `seq`。序号由数据库原子递增，可用于断线续读和审计。

## 3. DAG 与状态机

Plan Queue 后才能被 worker claim。Task 仅在所有前驱均为 `skipped / succeeded` 时可执行；任一前驱为 failed、canceled 或 blocked，当前 Task 进入 blocked。

```text
queued → running → succeeded
queued → running → queued      # 显式可重试失败或租约恢复
queued → running → failed
queued/running → canceled
queued → blocked
```

Plan 根据全部 Task 的持久化状态归并，不依赖内存 Future 判断完成。

## 4. Claim、Heartbeat 与恢复

Claim 使用数据库条件更新：

- Task 仍为 queued；
- `available_at` 已到；
- 未请求取消；
- lease 为空或过期；
- Plan 仍为 queued / running；
- 前驱已经成功。

只有一个 worker 能把 Task 原子切换为 running，并创建下一编号 Attempt。Heartbeat 同时刷新 Task 和当前 Attempt，可附带 checkpoint 与 Usage。

恢复扫描处理：

1. claim lease 到期，Attempt 进入 interrupted；
2. 从 Attempt 启动时间计算的 timeout 到期，Attempt 进入 timed_out。

仍有 attempt 预算时 Task 回到 queued，否则进入 failed。旧 worker 随后的 complete / fail 因 token 失效而冲突。

## 5. 通用 Worker 与失败策略

`TaskRuntimeEngine` 提供：

- 固定 worker 池；
- Plan kind 作用域；
-显式 `task_type → handler` 注册；
- 自动 heartbeat；
- 周期恢复扫描；
- cooperative cancel；
- fail-closed 的未知 Handler 行为。

未知任务类型直接失败。普通未捕获异常默认不重试；只有 Handler 抛出 `RetryableTaskError`，或 Task Policy 明确允许 `retry_unhandled` 时，才会消费下一次 attempt。这样不会因为一个未分类异常自动重复副作用。

## 6. Agent Turn 生产接入

### 6.1 原子创建

```http
POST /api/conversations/{conversation_id}/turns
```

同一事务写入：

1. 用户消息；
2. AgentTurn；
3. `agent.turn` RuntimePlan；
4. `agent.turn.execute` RuntimeTask；
5. Plan queued 状态与事件。

响应同时返回 `turn_id` 与 `runtime_plan_id`。即使请求提交后进程立即退出，数据库中仍有完整执行意图。

### 6.2 启动与无人值守恢复

FastAPI startup 会启动 Agent RuntimeEngine。queued Plan 会直接执行；running 但 lease 过期的 Task 会被 recovery 重新排队。恢复不依赖用户重新打开页面。

读取 Turn 或订阅 SSE 仍会执行一次低成本 wake-up，用于减少延迟，但它们不再是恢复前提。

### 6.3 Checkpoint

Agent RuntimeTask checkpoint 冻结：

- provider ID 与 model ID；
- system/context/history messages；
- `model / tools / finalize / done` phase；
- 当前 round；
- 已确定的 tool calls；
- 当前 tool index；
- Prompt / completion Usage；
- final text 与 assistant message ID。

恢复时显式把冻结的 `model_id` 传给 Adapter；当前默认模型后来改变也不会改变旧 Turn 的恢复语义。若冻结模型已被删除，Turn 失败关闭，而不是静默切换模型。

## 7. 工具调用的 exactly-once 边界

每个逻辑工具调用根据以下输入得到稳定 Step ID：

```text
turn_id
round
call_index
provider_call_id
tool_name
canonical arguments
```

Agent mutating tool 继续通过 CommandBus，幂等键为：

```text
agent:{turn_id}:{stable_step_id}
```

因此关键崩溃窗口的行为为：

| 窗口 | 恢复行为 |
| --- | --- |
| ToolCall 已写入 checkpoint，尚未执行 | 从同一 logical call 创建同一 Step |
| Command 已提交，Step 尚未完成 | 重放同一个 Operation，不重复实体 |
| Step 已完成，tool index 尚未 checkpoint | 读取已完成 Step 结果，不重做副作用 |
| 多次 RuntimeTask Attempt | 继续使用相同 logical call 与 Operation key |
| 恢复时工具名或参数改变 | 冲突失败，不接受漂移意图 |

这使 `write_artifact`、`create_units`、`generate_media` 和提案工具在已验证窗口内不会因为 Agent 进程重启而重复创建业务实体。

## 8. SSE 与事件恢复

Agent 的结构化事件写入 RuntimeTaskEvent：

```text
agent.step.start
agent.step.done
agent.entity
agent.error
agent.message
agent.done
```

SSE 使用：

```http
GET /api/conversations/{conversation_id}/stream
    ?turn_id=...
    &last_event_id={turn_id}:{seq}
```

服务端从最后一个持久序号之后补发。实时 token 为低延迟展示事件，明确标记 `durable=false`，不作为 Last-Event-ID；最终 `agent.message` 会用已提交的完整助手消息替换可能缺失或重复的 token 文本。

前端按稳定 Step ID 和实体 ID 幂等归并。即使断线后结构化事件重放，也不会增加第二个 Step 或实体。

## 9. 终态提交后的断电窗口

AgentTurn、assistant message 和 RuntimeTaskEvent 不在同一业务事务中。若进程在终态事实提交后、事件追加前退出，新 Attempt 会根据持久化事实补齐缺失的：

- step.start / step.done；
- entity；
- message；
- done。

补齐逻辑先读取现有事件，只追加缺失语义，因此同一终态事件不会重复写入。随后 RuntimeTask 才进入 succeeded。

## 10. Cancel 与失败

Cancel 会在数据库中：

- 把 RuntimePlan、非终态 Task 和 running Attempt 标记为 canceled；
- 清除 claim；
- 把 AgentTurn 标记为 canceled；
- 追加持久化 `agent.done`；
- 拒绝旧 worker 的迟到写入。

Agent Handler 的暂时性异常最多按 Task 的 attempt 策略重试。最终失败时，错误 Step、失败助手消息、AgentTurn failed、`agent.error / message / done` 均被持久化。

## 11. 可观察接口

当前通用 HTTP 写入仍由内部应用服务控制；外部只暴露诊断查询：

```http
GET /api/projects/{project_id}/runtime-plans
GET /api/runtime-plans/{plan_id}
GET /api/runtime-tasks/{task_id}
GET /api/runtime-plans/{plan_id}/events?after_seq=0
```

列表返回 Plan 摘要；详情返回 Task 与全部 Attempt；事件接口按 `after_seq` 增量读取。

## 12. 已验证不变量

自动测试覆盖：

- DAG 前驱释放与 blocked 传播；
- 同一业务 key 的并发 Plan 创建只提交一份；
- 多 worker 唯一 claim；
- heartbeat、lease、timeout、恢复与迟到写入拒绝；
- retry backoff 和 attempt 上限；
- Cancel；
- Handler registry 和未知任务 fail-closed；
- Plan 事件连续序号与分页续读；
- Turn / RuntimePlan 原子创建；
- Agent startup 自动执行 queued Plan；
- LLM / tool-loop checkpoint；
- 冻结 Provider / Model；
- Command 已提交但 Step / checkpoint 未提交时不重复实体；
- final assistant message 不重复；
- 终态事实提交后缺失事件自动修复；
- SSE 持久化重放和非持久 token 游标隔离；
- 现有 JSON 工具协议、取消、撤销和工作台回归；
- fresh / pre-Alembic 数据库升级；
- 后端、前端测试、lint、设计检查与生产构建。

## 13. 当前边界

尚未完成：

1. Planner、Executor、Reviewer、Repair 的领域分层；
2. 可持久化、可审计的 PolicyDecision 与确认任务；
3. token、成本、步骤数和媒体预算的执行期硬限制；
4. 通用 RuntimePlan Replan lineage；
5. 通用 Task compensation；
6. PostgreSQL 多进程竞争、网络分区和大规模故障注入基线；
7. token 级持久化流输出；当前只保证结构化事件和最终消息恢复；
8. 将 RegenerationPlan 迁入通用 Runtime，当前避免双写和过早抽象。

## 14. 回滚

Runtime 表与 AgentTurn、OperationLog、Artifact 记录均描述已发生事实。回滚应用代码不应删除这些记录。数据库 downgrade 会按 Event → Attempt → Task → Plan 删除通用运行时表，但生产回滚应优先保留表，等待兼容版本继续恢复或审计。
