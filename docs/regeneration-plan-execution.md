# 持久化级联修复计划

> 状态：多进程安全的 Step 租约、失败 Retry、当前图 Replan 与工作台闭环均已实现。  
> 日期：2026-08-12。  
> 适用范围：Artifact 依赖图中的 LLM 重新生成、Timeline 重编译与缺失素材替换。

## 1. 执行模型

级联修复不能由一个父 Job 同步等待多个子 Job。那种模型会占住 worker、把状态留在内存，并在进程重启或并发协调时产生重复任务。

当前实现由三个持久化对象组成：

```text
RegenerationPlan
  └─ RegenerationPlanStep
       └─ Job / 本地 Command Operation

RegenerationPlan ──replan lineage──> RegenerationPlan
```

协调器只执行短事务：读取状态、原子抢占一个可执行 Step、提交副作用、持久化结果，然后返回。外部 Job 完成后由 Job 回调、应用启动恢复或周期 reaper 再次推进计划。

## 2. 数据模型

### 2.1 RegenerationPlan

计划冻结：

- 项目、根 Artifact 与 `include_downstream`；
- 预览快照 SHA-256；
- `draft / running / blocked / succeeded / failed / canceled`；
- `execution_attempt`；
- 运行摘要、错误、起止时间。

### 2.2 RegenerationPlanStep

每个 Artifact 对应一个 Step，冻结：

- Artifact ID、名称、类型、Unit 与 `expected_version_id`；
- 拓扑顺序、计划内前驱和选择外上游；
- 动作、blocker、缺失素材；
- 来源 Job 与当前运行 Job；
- 用户结构化输入；
- 结果版本、错误和时间戳；
- `execution_attempt` 与不可变 `attempt_history`；
- `claim_token / claim_owner / claim_until / claim_attempt`。

Step 不外键引用目标 Artifact 或 ArtifactVersion。目标被删除后，计划仍保留可审计快照并能解释失败。

### 2.3 RegenerationPlanReplan

Replan 关系保存：

- source / target Plan；
- source 原状态与执行尝试；
- target 当前图快照；
- 原因与时间。

每个 source 只允许一个直接 target，每个 target 只允许一个直接 source。因此多次 Replan 形成可遍历的线性 lineage，而不是同一旧计划分叉出多个可执行意图。

## 3. API

```http
POST /api/projects/{project_id}/artifact-regeneration/preview
POST /api/projects/{project_id}/artifact-regeneration/plans
GET  /api/projects/{project_id}/artifact-regeneration/plans
GET  /api/artifact-regeneration/plans/{plan_id}
POST /api/artifact-regeneration/plans/{plan_id}/start
POST /api/artifact-regeneration/plans/{plan_id}/retry
POST /api/artifact-regeneration/plans/{plan_id}/replan
GET  /api/artifact-regeneration/plans/{plan_id}/lineage
POST /api/artifact-regeneration/steps/{step_id}/input
POST /api/artifact-regeneration/plans/{plan_id}/cancel
```

Plan Create 与 Replan 都接受稳定的 `client_token`。同一次网络失败或重复提交重放原 Operation；一次成功意图完成后，浏览器为下一次意图生成新 token。

## 4. 创建与启动

创建计划时服务端重新计算预览并冻结快照，不信任客户端提交的拓扑或动作。

Start Operation 在一个事务中验证：

1. Plan 仍非终态；
2. 快照一致；
3. 每个目标仍指向冻结的当前版本；
4. Artifact 仍存在并属于当前项目。

目标被人工修改后，Start 返回冲突。旧计划不会悄悄套到新版本上。

Start 不是可逆 Operation。它可能已经创建外部 Job 或追加本地版本；Cancel 只能停止未完成工作，不能删除已经完成的历史版本。

## 5. 数据库级 Step claim

多个应用进程可以同时扫描同一个 running Plan。真正的唯一执行权由数据库 CAS 获得，而不是进程内锁：

```text
UPDATE regeneration_plan_steps
SET claim_token = ..., claim_owner = ..., claim_until = ...
WHERE id = ...
  AND status IN (ready, waiting_for_predecessors)
  AND claim 已空或已过期
  AND 所属 Plan = running
```

只有更新成功的协调器可以派发副作用。完成或关联 Job 时还必须再次匹配同一个 `claim_token`。因此：

- 两个协调器只会有一个 claim winner；
- 租约过期后其他进程可以接管；
- Cancel 会清除租约，旧 owner 的迟到完成写入被拒绝；
- 终态 Plan / Step 不能被旧协调器写回 running；
- `claim_attempt` 保留每次抢占次数，便于审计。

默认租约为 120 秒。外部 Job 的长期运行不依赖 Step claim；Step 在 Job 创建并关联后立即进入 `queued`，租约随之释放。

## 6. Step 动作与幂等

### 6.1 LLM Artifact

当前前驱全部为 `skipped / succeeded` 时，协调器基于 Provenance 与来源 Job 构造新的生成 Job。第一次执行使用：

```text
regeneration-plan:{plan_id}:step:{step_id}
```

Retry 后使用：

```text
regeneration-plan:{plan_id}:step:{step_id}:attempt:{n}
```

Job payload 同时保存 `_regeneration_plan_step_attempt`。Job 回调只有在 Job ID 与 Step 当前 attempt 一致时才能推进该 Step。

### 6.2 Timeline 重编译

不缺素材的 stale Timeline 通过 `RecompileTimelineArtifactCommand`：

- 再次检查目标版本；
- 刷新当前上游版本；
- 重新编译；
- 追加 Timeline 版本并登记新依赖。

### 6.3 Timeline 素材替换

直接缺失 Asset 的 Timeline 进入 `requires_input`。替换映射必须：

- 覆盖每个直接缺失 Asset；
- 使用不同目标 Asset；
- 属于当前项目；
- 保持原 Unit 作用域；
- 类型相同，或在 image / video 视觉素材家族内兼容。

输入可在启动前写入，也可以让已启动但 blocked 的 Plan 恢复执行。

## 7. 崩溃与并发恢复

恢复依赖四层不变量：

1. 数据库 Step claim；
2. Step attempt 级 Operation 幂等键；
3. CreateJobCommand 的业务幂等；
4. Job 输出持久化的 Job / 槽位幂等。

| 中断窗口 | 恢复行为 |
| --- | --- |
| Step 已 claim，尚未执行 | 租约过期后其他进程接管 |
| Job 已创建，Step 尚未写入 `job_id` | 重放同一 Step Operation，取得同一 Job 后补链 |
| ArtifactVersion 已提交，Job result 尚未更新 | 重放输出 Operation，不追加第二版 |
| Job 已成功，worker 尚未通知 Plan | 启动恢复或 reaper 扫描 Job 终态并释放后继 |
| Timeline Command 已提交，Step 尚未完成 | 重放同一 Operation，读取原结果 |
| Plan 已取消，旧 owner 才返回 | claim token 已失效，迟到写入被拒绝 |
| 应用重启时 Plan 为 running | JobEngine 启动与周期 reaper 恢复 |

## 8. Retry

Retry 不是复活旧 Job，而是同一 Plan 的新执行尝试。

允许 Retry 的前置条件：

- Plan 状态为 `failed`；
- 客户端提交的 `expected_execution_attempt` 仍匹配；
- 没有 queued/running 子 Job；
- 没有有效 Step claim；
- 不包含 canceled Step；
- 失败目标和已成功结果仍是当前版本；
- 未超过 20 次安全上限。

Retry 会：

1. 把失败 Step 的 Job、输入、结果、blocker、错误和时间写入 `attempt_history`；
2. 增加 Plan 与失败 Step 的 attempt；
3. 只重置失败 Step，保留成功 Step 与其版本；
4. 为新尝试使用新的 Operation 幂等键；
5. 拒绝旧 Job 回调覆盖当前 `job_id`。

同一 `expected_execution_attempt` 的网络重放只返回同一次 Retry 结果，不会再次递增 attempt。

## 9. Replan

Retry 适用于“原计划仍正确，只是某次执行失败”。Replan 适用于目标版本漂移、依赖图变化、计划被取消或 blocker 需要重新计算。

Replan：

1. 从旧 Plan 继承根 Artifact 与 `include_downstream`；
2. 重新读取当前依赖图、Freshness、目标版本、动作和 blocker；
3. 计算新的快照；
4. 在同一事务中把旧执行意图终止为 canceled；
5. 创建新的 draft Plan；
6. 写入唯一 lineage 关系。

允许的 source 状态为 `draft / blocked / failed / canceled`。仍有活动 Job 或有效 claim 时拒绝 Replan。

原子退休 source 是关键不变量：Replan 与旧 Plan 的 Start/Retry 竞争时，只能有一个状态 CAS 胜出，不会留下两个同时可执行的计划。

## 10. Cancel

Cancel 会：

- 先把 Plan 原子切换为 canceled；
- 把所有非终态 Step 切换为 canceled并清除 claim；
- 为已关联 Job 设置 `cancel_requested`；
- 向当前进程 worker 发送协作式取消信号。

Cancel 不保证撤回已经完成或不支持取消的外部 Provider。已成功版本仍是历史事实，不做删除式回滚。

## 11. 工作台

内容状态中心支持：

- 只读级联预览；
- Plan 创建、Start、Cancel；
- 缺失素材选择；
- 运行状态轮询；
- 最近 Plan 重开；
- 失败 Step Retry 与 attempt history；
- 当前图 Replan；
- source / target lineage 导航。

界面明确区分：

- **Retry**：保留当前 Plan 与成功版本，只重跑失败 Step；
- **Replan**：终止旧意图，按当前图创建新 draft Plan。

## 12. 已验证不变量

自动测试覆盖：

- 双协调器只派发一个子 Job；
- claim 过期接管、Cancel 后迟到 owner 拒绝；
- 终态状态不可复活；
- 拓扑逐步释放与回调丢失恢复；
- Retry 历史、新 attempt 幂等键和旧 Job 隔离；
- Retry 目标版本漂移拒绝；
- Replan 当前图、lineage、唯一后继和 client token 重放；
- Replan 等待活动 Job 终态；
- Replan 原子退休 source，旧 Plan 不能再 Start；
- Alembic fresh / legacy 升级；
- 后端测试、前端测试、lint、设计检查与生产构建。

## 13. 当前边界

尚未完成：

1. 多个独立分支部分失败时的可配置继续策略；
2. `requires_review` 的确认与继续接口；
3. 已完成 Step 的自动补偿或版本回退；
4. 外部 Provider 的强制取消与迟到输出策略；
5. 500 节点计划的压力、故障注入和生产数据库竞争基线；
6. 将生成 Asset 建模为可传播 Freshness 的生产节点；
7. 更多故事结构 → 剧本 → 镜头 → 分镜生产链的自动依赖登记。

## 14. 回滚

回滚协调器或界面代码不会删除 Plan、Step、Replan lineage、Job、Operation 或 ArtifactVersion。它们是历史审计记录。内容恢复应追加新版本，不改写或删除已经发生的事实。
