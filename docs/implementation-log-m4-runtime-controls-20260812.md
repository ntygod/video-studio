# M4.3 运行时控制面：数据库准入与事件语义去重

> 分支：`refactor/kernel-v2-foundation`  
> 日期：2026-08-12  
> Alembic revision：`20260812_0011`

## 目标

M4.2 已让 Agent Turn 进入通用 RuntimeTask worker，但仍有两个可靠性边界：

1. 进程在 AgentStep 事实提交与 checkpoint 推进之间退出时，结构化事件可能重放；
2. RuntimePlan 已持久化后，不再受旧内存队列的 `max_queued` 约束，持续流量可能形成无界积压。

本轮把这两项约束下沉到数据库，使多进程和重启后的行为仍由持久化事实决定。

## 数据模型

新增三张表：

```text
runtime_admission_buckets
runtime_admission_reservations
runtime_event_dedupes
```

### Admission Bucket

Bucket 以 RuntimePlan kind 为键保存容量。当前迁移默认建立：

```text
agent.turn → 10
```

容量 10 与默认 `2 workers + 8 queued` 一致。

### Admission Reservation

Plan 在 `queue_plan` 事务内占用一个编号 slot。活动 slot 使用数据库部分唯一索引：

```text
UNIQUE(bucket_key, slot) WHERE released_at IS NULL
```

并发进程争用同一 slot 时只有一个事务成功。Plan 进入 `blocked / succeeded / failed / canceled` 后，在同一状态转换事务中释放 slot。Plan 或 Project 被级联删除时，Reservation 也被数据库删除，因此不依赖进程内计数和清理线程。

容量已满时抛出 `RuntimeAdmissionFull`，HTTP 映射为：

```http
429 Too Many Requests
Retry-After: 2
```

Turn 的用户消息、AgentTurn、RuntimePlan 和 RuntimeTask 与准入预留处于同一个 UnitOfWork；拒绝会整体回滚，不留下半条消息或孤儿 Turn。

### Event Dedupe

`runtime_event_dedupes` 把语义身份映射到首条 RuntimeTaskEvent。当前覆盖：

- `agent.step.start:{step_id}`；
- `agent.step.done:{step_id}`；
- `agent.entity:{type}:{id}`；
- `agent.proposal:{proposal_id}`；
- `agent.message:{turn_id}`；
- `agent.done:{turn_id}`。

Dedupe marker 与事件写入同一事务。并发或恢复重放命中已有 marker 时返回原事件 ID 与 seq，不递增 Plan event_seq，也不追加第二条审计事件。前端同时只接受更大的持久化 seq 作为下一次续读游标；旧事件即使被实时重放，也不能让 `last_event_id` 倒退。

迁移会扫描已有 Agent 事件，并为每个语义身份的第一条事件建立 marker；历史重复事件保留为审计事实，但不会继续增长。

## 不变量

本轮建立以下可验证不变量：

1. 同一 Bucket 的活动 Reservation 数不会超过 capacity；
2. Plan 未成功预留 slot 时不能进入 queued；
3. Plan 终态与 slot 释放位于同一数据库事务；
4. 同一 Agent 结构事件的语义身份最多对应一条新 RuntimeTaskEvent；
5. admission 拒绝不会提交用户消息、Turn 或 Plan；
6. 进程重启不重置容量，也不清空排队事实。

## 回滚

应用代码回滚前应先停止创建依赖 admission 的新 Plan。Alembic downgrade 会按以下顺序删除：

```text
runtime_event_dedupes
runtime_admission_reservations
runtime_admission_buckets
```

现有 RuntimePlan、RuntimeTask、Attempt 和 Event 不会被删除。降级后系统恢复为无数据库准入与无语义 marker 的 M4.2 行为。

## 后续

- 将 Bucket 配置暴露为受控运维配置，而不是固定迁移默认值；
- 为不同 Project 或租户增加独立配额作用域；
- 将预算、token、媒体成本和 wall-clock 限制纳入 claim 前 Policy；
- 在 PostgreSQL 多进程环境执行高并发 slot 争用与故障注入基线。
