# M4 通用耐久任务运行时

> 状态：基础内核与只读可观察接口已实现；Agent 尚未切换为该运行时的执行源。  
> 日期：2026-08-12。  
> Alembic revision：`20260812_0010`。

## 1. 目的

M3 的 `RegenerationPlan / RegenerationPlanStep` 验证了数据库租约、拓扑释放、崩溃恢复、Retry 与 Replan，但它仍然是 Artifact 修复领域模型。M4 把已经成立的执行不变量抽成领域无关运行时：

```text
RuntimePlan
  └── RuntimeTask DAG
        └── RuntimeTaskAttempt
              └── RuntimeTaskEvent
```

第一阶段只建立一个可以被 Agent、模型、媒体、渲染和评估逐步采用的稳定执行内核，不立即重写现有业务协调器。

## 2. 数据模型

### RuntimePlan

Plan 表示一次用户或系统执行意图，保存：

- 项目、kind 和 subject；
- 可选业务幂等键；
- `draft / queued / running / blocked / succeeded / failed / canceled`；
- 输入、Policy、预算、累计 Usage、结果与错误；
- 单调事件序号和起止时间。

### RuntimeTask

Task 是 DAG 节点，保存：

- Plan 内稳定 `task_key` 与 `task_type`；
- 前驱 Task ID；
- payload、Policy、checkpoint、Usage 和结果；
- attempt 上限、timeout 与下次可执行时间；
- cancel 标志；
- 数据库 claim token、owner、lease 和 claim 次数。

### RuntimeTaskAttempt

每次成功 claim 都创建不可变编号的新 Attempt。Attempt 保存 worker、claim token、checkpoint、Usage、结果、错误、是否可重试、心跳、lease 和终态。旧 Attempt 永远不会被新尝试覆盖。

### RuntimeTaskEvent

事件使用 Plan 内单调 `seq`，记录 Plan、Task、Attempt、事件类型和结构化 payload。序号通过数据库原子递增产生，可用于断线续读和后续 SSE。

## 3. 状态与依赖

Plan 在 Queue 后才允许 worker claim。Task 只有在所有前驱均为 `skipped / succeeded` 时可执行；任一前驱为 failed、canceled 或 blocked，当前 Task 会进入 blocked。

状态由持久化事实归并：

```text
queued → running → succeeded
queued → running → queued   # 可重试失败或租约恢复
queued → running → failed
queued/running → canceled
queued → blocked
```

Plan 不依赖内存 Future 推断完成状态，而是根据全部 Task 状态计算终态。

## 4. Claim、Heartbeat 与崩溃恢复

Claim 使用数据库条件更新：

- Task 仍为 queued；
- `available_at` 已到；
- 未请求取消；
- lease 为空或过期；
- Plan 仍为 queued / running；
- 前驱已成功。

只有一个 worker 能把 Task 原子切换为 running 并创建下一编号 Attempt。Heartbeat 同时更新 Task 和当前 Attempt 的 lease，可附带 checkpoint 与 Usage。

恢复扫描处理两种中断：

1. claim lease 到期，Attempt 进入 interrupted；
2. 从 Attempt 启动时间计算的 timeout 到期，Attempt 进入 timed_out。

仍有 attempt 预算时 Task 回到 queued，否则进入 failed。旧 worker 的 claim token 已失效，迟到 complete / fail 会冲突，不得覆盖新 Attempt。

## 5. Retry、Backoff 与 Cancel

Handler 失败时可以声明是否可重试，并给出 backoff。只有同时满足下列条件才重新排队：

- 失败被标记为 retryable；
- `attempt_count < max_attempts`；
- Plan 仍活动；
- Task 未取消。

Cancel 原子终止 Plan 和所有非终态 Task，清除 claim，并把运行中的 Attempt 记为 canceled。旧 worker 随后的完成写入会因失去 claim 而被拒绝。

## 6. 应用接口

内部应用层使用 `TaskRuntime`：

```python
runtime.create_plan(...)
runtime.claim_next(...)
runtime.heartbeat(...)
runtime.complete(...)
runtime.fail(...)
runtime.cancel(...)
runtime.recover(...)
runtime.events(...)
```

当前 HTTP 只暴露只读可观察接口，避免外部调用者绕开 CommandBus 或 Worker Policy 直接操纵状态：

```http
GET /api/projects/{project_id}/runtime-plans
GET /api/runtime-plans/{plan_id}
GET /api/runtime-tasks/{task_id}
GET /api/runtime-plans/{plan_id}/events?after_seq=0
```

列表返回 Plan 摘要；详情返回 Task 与全部 Attempt；事件接口使用 `after_seq` 增量读取。

## 7. 已验证不变量

自动测试覆盖：

- DAG 只按前驱成功顺序释放；
- 同一业务幂等键返回同一 Plan；
- 两个 worker 并发时只有一个获得 Task；
- lease 过期产生新 Attempt，旧 claim 不能迟到提交；
- retry backoff 和 max attempts；
- timeout；
- Cancel 终止 Attempt 并拒绝旧 worker 写入；
- 缺失依赖与依赖环拒绝；
- Plan 事件序号连续且支持分页续读；
- fresh 和 pre-Alembic 数据库升级。

## 8. Agent 迁移边界

当前 Agent 回合仍使用固定内存 worker。不能仅把同一个 `run_turn` 包在 RuntimeTask 外就宣称安全恢复：现有 Agent 工具幂等键包含一次性的 `AgentStep.id`，崩溃后若从头重新调用模型，可能产生新的 Step ID 并重复副作用。

Agent 迁移必须先完成：

1. 持久化 LLM / tool-loop checkpoint；
2. 为逻辑工具调用提供跨 Attempt 稳定身份；
3. 崩溃后复用原 Operation 幂等键；
4. 恢复模型 messages、已完成工具结果和 token Usage；
5. 证明“工具已提交但 checkpoint 未写”的窗口不会重复实体；
6. 让 SSE 从 RuntimeTaskEvent 续读，而不只依赖进程内回调。

完成这些条件后，Agent 才能成为通用运行时的首个生产消费者。

## 9. 当前边界

- 尚无通用 Worker / Handler registry；
- 尚无公开写 API；
- PolicyDecision 仍只预留 JSON 契约；
- 预算尚未在 claim 或 handler 中强制执行；
- 尚无通用 Replan lineage；
- RegenerationPlan 暂不迁移，避免在通用运行时稳定前制造双写；
- 真实 PostgreSQL 多进程竞争和大图压力仍待验证。

## 10. 回滚

运行时表目前没有接管现有业务写入。回滚应用代码不会影响 RegenerationPlan、Job、AgentTurn 或 Artifact；`runtime_*` 表可以保留为审计数据。数据库 downgrade 会按 Event → Attempt → Task → Plan 顺序删除新表。
