# M4 实施记录 · 2026-08-12

> 分支：`refactor/kernel-v2-foundation`。  
> 当前阶段：M4.1 通用执行内核 + M4.2 Agent Turn 首个生产闭环。

## 1. 通用运行时模型

新增 Alembic `20260812_0010`：

- `runtime_plans`；
- `runtime_tasks`；
- `runtime_task_attempts`；
- `runtime_task_events`。

Plan 保存业务意图、Policy、预算、Usage 和单调事件序号；Task 保存 DAG、payload、checkpoint、attempt 策略、timeout 和数据库 lease；Attempt 保存每次 worker 所有权、心跳、checkpoint、Usage 与终态；Event 提供 Plan 内单调续读。

## 2. 状态机与并发

- Task DAG 在创建时验证缺失节点、自依赖和环；
- 前驱成功后才释放后继；
- 数据库 CAS 保证多 worker 唯一 claim；
- claim token 阻止旧 worker 迟到提交；
- heartbeat 同时刷新 Task 和 Attempt；
- lease 过期与 timeout 分别记录 interrupted / timed_out；
- retryable failure 支持 backoff 和 max attempts；
- Cancel 原子终止 Plan、Task 与 running Attempt；
- 同一 `kind + idempotency_key` 的并发 Plan 创建重放数据库胜者。

## 3. Worker / Handler Registry

新增 `TaskRuntimeEngine`：

- 固定 worker 池；
- kind 作用域；
- `task_type → handler` 注册；
- 自动 heartbeat 与周期 recovery；
- cooperative cancel；
- 未注册任务 fail-closed。

只有 `RetryableTaskError` 或明确 Policy 才触发新 Attempt。普通未捕获异常默认不重试，避免未知副作用重复执行。

## 4. 可观察接口

新增：

```http
GET /api/projects/{project_id}/runtime-plans
GET /api/runtime-plans/{plan_id}
GET /api/runtime-tasks/{task_id}
GET /api/runtime-plans/{plan_id}/events
```

HTTP 暂不提供通用写入入口，避免绕开 CommandBus、领域前置条件和 Worker Policy。

## 5. Agent logical tool call

新增稳定 Agent Step 身份：

```text
stable_step_id = hash(turn_id, logical_call_id)
```

logical call 由 round、call index、Provider call ID、工具名和规范化参数确定。恢复必须得到相同工具名与参数，否则冲突失败。

mutating tool 使用原有 CommandBus，并把稳定 Step ID 写入：

```text
agent:{turn_id}:{stable_step_id}
```

故障注入验证 Command 已提交、Step 尚未完成的窗口只重放原 Operation，不重复 Artifact 或 OperationLog。

## 6. Agent tool-loop checkpoint

RuntimeTask checkpoint 保存：

- 冻结的 Provider / Model；
- 完整 messages；
- model / tools / finalize / done phase；
- round、tool calls 和 tool index；
- Usage、final text 和 assistant message ID。

每个安全边界后 heartbeat 提交 checkpoint。恢复会从工具游标继续，而不是从头重新请求模型。冻结模型通过显式 `model_id` 恢复；模型消失时失败关闭。

## 7. Agent 生产路由迁移

Turn 创建现在在同一事务中提交：

- user message；
- AgentTurn；
- `agent.turn` RuntimePlan；
- `agent.turn.execute` RuntimeTask；
- queued 事件。

`DurableAgentTurnExecutor` 保留原 `submit` 兼容接口，但内存 Future 只用于当前请求的低延迟通知，不再拥有任务生命周期。

应用 startup 主动启动 Agent RuntimeEngine；读取 Turn 与订阅 SSE 也会 wake worker，但不是恢复前提。

## 8. SSE 与终态修复

结构化 Agent 事件写入 RuntimeTaskEvent，并按 `{turn_id}:{seq}` 续读。实时 token 标记为 `durable=false`，不会覆盖持久事件游标；最终 message 事件替换临时 token 文本。

补齐了“assistant message / AgentTurn 已提交，RuntimeTaskEvent 尚未提交即断电”的窗口。重启后依据 AgentTurn、Step、created entities 和 assistant message 只追加缺失事件，再完成 RuntimeTask。

## 9. 自动验收

新增和扩展测试覆盖：

- fresh / legacy 迁移；
- DAG、claim、heartbeat、timeout、recovery、retry、Cancel；
- 并发 Plan create；
- Handler registry 与 fail-closed；
- Runtime 可观察 API；
- stable tool call 和 Command replay；
- LLM / tool checkpoint；
- frozen model；
- Agent Turn 路由原子创建；
- startup 无浏览器恢复；
- cancel 终止 Plan / Task / Attempt；
- SSE 断线重放；
- 非持久 token 游标隔离；
- 终态提交后的事件修复；
- 原有 Agent、撤销、JSON tool protocol、前端 reducer 与构建回归。

CI 顺序为：

1. 全部后端测试；
2. 前端 Node 测试；
3. ESLint；
4. 设计检查；
5. Next.js 生产构建。

## 10. 明确保留的边界

- Planner / Executor / Reviewer / Repair 尚未分层；
- PolicyDecision 和人工确认尚未建模为耐久任务；
- Budget / Usage 尚未形成执行期硬门限；
- 通用 Replan 与 compensation 尚未实现；
- token 级输出不持久，只保证结构化事件与最终消息；
- PostgreSQL 多进程与系统性故障注入基线仍待建立；
- RegenerationPlan 暂不迁移，避免双写。

## 11. 回滚

M4 表是执行与审计事实。回滚 Agent 入口时应保留 RuntimePlan、Task、Attempt、Event、AgentTurn、Operation 与业务实体；后续兼容版本可以继续读取和恢复。不要通过删表或删除版本来伪装执行从未发生。
