# 持久化级联修复计划

> 状态：首个可恢复执行闭环已实现。  
> 日期：2026-08-12。  
> 适用范围：Artifact 依赖图中的 LLM 重新生成、Timeline 重编译与缺失素材替换。

## 1. 为什么不能把级联修复做成同步循环

依赖链可能跨越多个外部 Provider Job：

```text
上游输入 → LLM Artifact A → LLM Artifact B → Timeline
```

若一个父 Job 占据 worker 并同步等待每个子 Job，会造成 worker 饥饿、重启后丢失内存状态，并且无法可靠区分“子任务已提交”“输出已落库”“后继可释放”三个时刻。

因此执行模型由持久化 `RegenerationPlan` 与 `RegenerationPlanStep` 驱动。协调器只做短事务：读取状态、释放当前可执行步骤、持久化结果，然后立即返回。

## 2. 数据模型

### 2.1 RegenerationPlan

计划记录：

- 项目与根 Artifact；
- 是否包含当前下游；
- 预览快照 SHA-256；
- `draft / running / blocked / succeeded / failed / canceled`；
- 运行时摘要、错误和起止时间。

### 2.2 RegenerationPlanStep

每个被选择的 Artifact 对应一个步骤，冻结：

- Artifact ID、名称、类型和 Unit；
- `expected_version_id`；
- 拓扑顺序和前驱 Artifact ID；
- 建议动作；
- blocker、缺失 Asset 与外部上游；
- 来源 Job、运行时 Job；
- 用户结构化输入；
- 结果版本、错误和时间戳。

步骤不外键引用 Artifact 或 ArtifactVersion。这样目标被删除后，计划仍保留可审计快照并能解释失败原因。

## 3. API

```http
POST /api/projects/{project_id}/artifact-regeneration/preview
POST /api/projects/{project_id}/artifact-regeneration/plans
GET  /api/projects/{project_id}/artifact-regeneration/plans
GET  /api/artifact-regeneration/plans/{plan_id}
POST /api/artifact-regeneration/plans/{plan_id}/start
POST /api/artifact-regeneration/steps/{step_id}/input
POST /api/artifact-regeneration/plans/{plan_id}/cancel
```

创建计划时服务端重新计算预览，并要求快照哈希与请求前计算结果一致。浏览器为每次“创建”意图提供稳定 `client_token`：同一次失败重试重放原计划，创建成功后的下一次意图使用新 token，因此取消旧计划后可以基于相同图快照再建新计划。

## 4. 启动前置条件

Start Operation 在一个事务中验证：

1. 计划仍非终态；
2. 快照哈希一致；
3. 每个有目标版本的步骤仍指向同一个当前版本；
4. Artifact 仍存在并属于当前项目。

任何目标被人工修改后，Start 返回冲突，计划保持 `draft`。用户必须重新预览和创建计划，系统不会把旧计划悄悄套到新版本上。

Start 不是可逆 Operation。它可能已经释放外部 Job 或追加本地版本；取消只能停止未完成工作，不能删除已经完成的历史版本，因此 OperationLog 不声明 inverse。

## 5. 步骤释放

### 5.1 LLM Artifact

当所有计划内前驱都为 `skipped / succeeded` 时：

1. 从当前 Provenance 与来源 Job构造重新生成 specification；
2. 用最新上游 ArtifactVersion 和仍存在的 Asset 输入生成新 Job payload；
3. 使用确定性幂等键：

```text
regeneration-plan:{plan_id}:step:{step_id}
```

4. 创建并关联子 Job；
5. 协调器立即返回，不占用 worker 等待。

子 Job 成功后仍通过既有 Artifact 持久化 Operation 保持 Artifact ID、追加版本并登记新 Provenance。

### 5.2 Timeline 重编译

不缺素材的 stale Timeline 使用同一个步骤幂等键执行本地 `RecompileTimelineArtifactCommand`。命令再次检查目标版本，刷新当前上游版本，重新编译并追加 Timeline 版本。

### 5.3 Timeline 素材替换

直接缺失 Asset 的 Timeline 步骤进入 `requires_input`。用户必须为每个 tombstone 提供不同的兼容替代 Asset。系统校验：

- 当前项目；
- 原 Unit 作用域；
- 同类型，或 image / video 视觉素材互换；
- 替换映射完整且无重复目标。

输入可在计划启动前写入，也可以让已启动计划从 `blocked` 恢复为 `running` 并继续推进。

## 6. 崩溃恢复

恢复依赖三层幂等：

1. Plan Step 的确定性 Operation key；
2. CreateJobCommand 的业务幂等；
3. Job 输出持久化的 Job / 槽位幂等。

关键崩溃窗口：

| 窗口 | 恢复行为 |
| --- | --- |
| Job 已创建、Step 尚未写入 job_id | 重放 CreateJob Operation，取得同一个 Job 后补链 |
| Artifact 新版本已提交、Job result 尚未更新 | 既有持久化 Operation 重放，不追加第二版 |
| Job 已成功、worker 尚未通知 Plan | 启动 / reaper 扫描 Job 终态，标记 Step 成功并释放后继 |
| Timeline 本地命令已提交、Step 尚未完成 | 重放同一 Step Operation，读取原版本结果 |
| 服务重启时 Plan 为 running | JobEngine 启动和周期 reaper 调用协调器恢复 |

Job worker 在每次终态或重试切换后尝试推进所属 Plan；即使回调失败，持久化 Plan 保持 running，周期 reaper 会再次处理。

## 7. 状态与失败语义

步骤运行态包括：

```text
ready → queued/running → succeeded
waiting_for_predecessors → ready/queued
requires_input → ready/waiting_for_predecessors
```

`requires_review / manual / blocked` 不会自动执行。前驱失败、取消或不可解决时，后继进入 blocked。

当前首版策略是保守终止：任何步骤失败会把计划置为 failed；任何步骤取消会把计划置为 canceled。已经成功追加的 ArtifactVersion 不回滚，它们是可审计历史。取消会设置未完成子 Job 的 `cancel_requested` 并向本进程 worker 发送协作式取消信号，但外部 Provider 已完成或不支持取消时，迟到输出仍可能落库；计划状态不会因此自动恢复。

## 8. 工作台

内容状态抽屉同时展示：

- 最近持久化计划；
- draft / running / blocked / succeeded / failed / canceled；
- 已完成步骤数；
- 每一步动作、Job、错误和 blocker；
- 缺失素材替换编辑器；
- Start 与 Cancel。

运行中计划每 2 秒读取详细状态，计划摘要在存在 active Plan 时周期刷新。关闭弹窗或离开页面不影响执行；再次进入项目后可从最近计划列表恢复查看和输入。

## 9. 已验证不变量

自动测试覆盖：

- 三层 LLM 依赖只按拓扑逐步释放；
- 前驱 Job 成功前不创建后继 Job；
- Job 已成功但协调回调丢失时由恢复扫描继续；
- 同一计划恰好创建预期数量的子 Job；
- Start Operation 重放不重复创建任务；
- stale Timeline 本地重编译；
- 缺失 Asset 输入后自动续跑；
- Cancel 请求子 Job 取消；
- 目标版本漂移拒绝启动；
- 创建意图 token 的重试与重新创建语义；
- Alembic 新库与 legacy 库升级；
- 后端、前端测试、lint、设计检查和生产构建。

## 10. 当前边界

首版尚未覆盖：

1. 数据库级 Step claim；多应用进程部署应只运行一个 Plan 协调器；
2. 失败步骤的显式 Retry / Replan API；
3. 多个独立分支部分成功时的可配置继续策略；
4. `requires_review` 的确认与继续接口；
5. 已经完成步骤的自动补偿或版本回退；
6. 外部 Provider 的强制取消；
7. 500 节点计划的压力与故障注入基线；
8. 将生成 Asset 纳入可传播 Freshness 的统一生产图。

## 11. 回滚

回滚执行代码不会删除 Plan、Step、Job、Operation 或 ArtifactVersion。计划表是审计记录；已完成内容应通过版本恢复追加新版本，而不是改写历史。若回滚到不识别计划表的版本，数据库仍可保留新增表，后续升级可继续读取。
