# M4 实施记录 · 2026-08-12

> 分支：`refactor/kernel-v2-foundation`。  
> 阶段：M4.1 通用耐久任务运行时基础。

## 本轮完成

- 新增 Alembic `20260812_0010`；
- 新增 `runtime_plans`、`runtime_tasks`、`runtime_task_attempts` 与 `runtime_task_events`；
- 建立 Plan / Task / Attempt 的持久化状态机；
- 建立 Task DAG 验证与前驱释放；
- 建立数据库 CAS claim、lease、owner、token 与 claim attempt；
- 建立 heartbeat、checkpoint 和 Usage 持久化；
- 建立 retryable failure、backoff 和 max attempts；
- 建立 timeout 与 lease-expired recovery；
- 建立 Plan Cancel 和迟到 worker 写入拒绝；
- 建立 Plan 内单调事件序号；
- 新增 `TaskRuntime` 应用层事务边界；
- 新增 Plan、Task 与 Event 的只读可观察 API；
- 增加并发、恢复、重试、超时、取消、DAG、事件和迁移测试。

## 关键选择

### 不直接复制 RegenerationPlan

通用模型只保留执行所需的领域无关字段。Artifact target version、素材 blocker 和 Replan lineage 仍属于 M3 领域层；后续通过 payload、Policy 或领域适配器进入 RuntimeTask，而不是污染通用表。

### 不立即迁移 Agent

Agent 目前的副作用幂等作用域依赖 `AgentStep.id`。在没有持久化 tool-loop checkpoint 和稳定逻辑调用 ID 前，自动重跑可能重复创建 Artifact、Unit 或 Job。因此本轮先锁定运行时状态机，下一阶段专门处理 Agent crash window。

### HTTP 先只读

外部创建、claim、complete、retry 或 cancel 若绕过 CommandBus 和 Worker Policy，会形成第二套写入入口。当前只暴露诊断查询；业务写入继续由内部应用服务控制。

## 自动验收

CI 执行：

1. 全部后端测试；
2. 前端 Node 测试；
3. ESLint；
4. 设计检查；
5. Next.js 生产构建。

## 下一阶段

M4.2 聚焦 Agent durable checkpoint：

- RuntimeTask 作为 Agent Turn 的执行载体；
- LLM messages 与 tool-call 游标 checkpoint；
- 稳定 logical tool call ID；
- Operation 幂等键跨 Attempt 复用；
- RuntimeTaskEvent 驱动断线续读；
- 杀进程故障注入，证明不重复写入。
