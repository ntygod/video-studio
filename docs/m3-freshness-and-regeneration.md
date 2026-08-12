# M3：Dependency、Provenance、Freshness 与持久化修复

> 状态：精确输入、图传播、单点修复、级联预览、多进程执行、Retry 与 Replan 闭环已经成立。  
> 日期：2026-08-12。

## 1. M3 回答的问题

1. 一个产物使用了哪些不可变 ArtifactVersion 与 Asset？
2. 上游前进或素材删除后，哪些当前产物已经不可信？
3. 用户在哪里看到原因和后续影响？
4. 单个产物怎样安全修复并保留历史？
5. 多个产物应按什么顺序修复？
6. 多进程、重启、失败重试和重新规划如何不产生重复写入？

## 2. 数据模型

### 2.1 ArtifactDependency

连接精确上游 ArtifactVersion 与精确下游 ArtifactVersion。历史版本和历史边不可变；只有下游仍为当前版本的边参与传播和执行计划。

### 2.2 AssetDependency

连接 Asset 输入与 ArtifactVersion。上游 Asset 删除后边保留 tombstone 快照，可解释原名称、类型、Unit 和受影响版本。

### 2.3 ArtifactProvenance

记录：

- 精确输入版本；
- Provider / Model；
- Prompt version；
- 参数、seed、attempt；
- 负责持久化的 Operation。

### 2.4 ArtifactFreshness

| 状态 | 语义 |
| --- | --- |
| `fresh` | 没有已知失效输入 |
| `stale` | 上游 Artifact 已前进，当前版本仍使用旧版本 |
| `blocked` | 必需 Asset 或上游输入缺失 / 阻塞 |
| `needs_review` | 状态已注册，确认继续流程尚未完成 |

### 2.5 RegenerationPlan / Step / Replan

Plan 冻结根选择、图快照、状态和执行 attempt。Step 冻结目标版本、拓扑、动作、输入、租约、Job、attempt history 与结果。Replan 表保存旧 Plan 到新 Plan 的不可变 lineage。

Alembic 迁移链当前到：

```text
20260811_0005  AssetDependency
20260812_0006  RegenerationPlan / Step
20260812_0007  Step claim lease
20260812_0008  Retry attempt history
20260812_0009  Replan lineage
```

## 3. 生产输入登记

### 3.1 LLM Artifact

LLM Job 输出在同一个 Artifact 持久化 Operation 中登记输入、Provenance 与新版本。选择性重新生成会把旧上游 Artifact 替换为当前版本，并保留仍存在的 Asset 输入。

### 3.2 Agent 工具

`write_artifact` 与 `generate_media` 接受：

- `input_version_ids`；
- `input_artifact_ids`；
- `input_asset_ids`。

系统还读取当前 Turn 的 `context_refs` 和项目 `pinned_refs`。Artifact 引用在首次提交事务中冻结为当前版本；跨项目输入失败。

Unit、项目、Bible 与普通 Prompt 文本不会被猜测或展开为隐藏依赖。详见 `docs/agent-explicit-production-inputs.md`。

`write_artifact` 创建正式 Artifact / Asset 依赖和 Provenance。媒体 Job 将输入冻结进 Job payload，并保留在生成 Asset metadata 中；生成 Asset 当前还不是 Freshness 节点。

### 3.3 Timeline

Timeline 编译登记实际采用的 edit plan 版本与 clip Asset。重编译或素材替换只追加新版本并登记新依赖，旧版本与 tombstone 保留。

## 4. 状态传播

### 4.1 Artifact 前进

上游追加新当前版本时：

1. 上游恢复 fresh；
2. 查找仍为当前版本、但使用上游历史版本的下游；
3. 标记 stale；
4. 沿当前依赖图递归传播。

### 4.2 Asset 删除

删除被当前版本使用的 Asset 时：

1. tombstone 保留；
2. 直接下游进入 blocked；
3. 缺失 Asset ID 沿 Artifact 图递归传播；
4. 单元子树删除先阻塞仍存活的外部下游，再执行数据库级联。

### 4.3 图安全

拒绝：

- 自依赖；
- 直接或间接环；
- 跨项目边；
- 单次超过 500 个输入；
- 项目超过 50,000 条 Artifact 边或 100,000 条 Asset 边。

## 5. 查询与修复 API

```http
GET  /api/artifact-versions/{version_id}/provenance
GET  /api/artifacts/{artifact_id}/freshness
GET  /api/artifacts/{artifact_id}/dependencies
GET  /api/artifacts/{artifact_id}/asset-dependencies
GET  /api/assets/{asset_id}/dependents
GET  /api/artifacts/{artifact_id}/impact
GET  /api/projects/{project_id}/artifact-freshness
POST /api/artifacts/{artifact_id}/regenerate
POST /api/artifacts/{artifact_id}/repair-assets
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

项目 Freshness 默认只返回待处理内容，优先级为：

```text
blocked → stale → needs_review → fresh
```

## 6. 单点修复

### 6.1 LLM 选择性重新生成

只接受 stale、未锁定、具备完整可重放来源、上游均 fresh 且 Asset 仍存在的 Artifact。保持 Artifact ID，只追加版本。默认幂等键包含目标当前版本。

### 6.2 Timeline 素材修复与重编译

缺失素材修复要求完整兼容映射；普通 stale Timeline 可刷新当前上游后重新编译。两者均再次检查目标版本并追加新版本。

## 7. 级联预览

只读预览从根 Artifact 出发，可扩展当前下游，返回稳定拓扑、目标版本、动作、前驱、外部上游、blocker 和自动执行能力。预览不创建 Job、Operation、Plan 或版本。

详见 `docs/regeneration-cascade-preview.md`。

## 8. 持久化执行

协调器按拓扑释放 Step：

- 数据库 CAS claim 决定多进程唯一 owner；
- LLM Step 创建持久化子 Job 后立即释放协调器；
- Timeline Step 执行本地幂等 Command；
- 前驱失败或不可解决时后继 blocked；
- Job 终态回调、应用启动和周期 reaper 共同恢复 running Plan；
- claim token、状态 CAS 和 attempt ID 阻止迟到写入。

## 9. Retry 与 Replan

### Retry

适用于图和目标仍正确、只是执行失败。只重置失败 Step，保留成功版本，并把旧失败快照写入 attempt history。新 attempt 使用新的 Operation key，旧 Job 回调不能覆盖当前 attempt。

### Replan

适用于图、目标版本或 blocker 已变化。重新读取当前图，原子终止旧执行意图，创建新 draft Plan，并登记唯一 lineage。旧 Plan 不能再 Start 或 Retry。

完整契约见 `docs/regeneration-plan-execution.md`。

## 10. 工作台

工作台提供：

- Freshness 数量、原因、影响范围和版本深链；
- 单项重新生成与级联预览；
- Plan 创建、Start、Cancel；
- 素材替换输入；
- 运行状态与最近计划；
- 失败 Retry、attempt history；
- 当前图 Replan 与 lineage 导航。

stale / blocked 内容不能直接采用或锁定。

## 11. 可观察性与幂等

- 所有写入通过 CommandBus / OperationLog；
- Freshness 副作用合并进触发 Operation 的 affected entities；
- 大 payload 只在业务表保存，OperationLog 使用指纹和稳定引用；
- Job 输出按 Job / 槽位重放；
- Agent 工具按 turn / step 重放；
- Plan Create / Replan 按 client intent token 重放；
- Plan Step 按 attempt 级幂等键重放；
- 目标版本在 Start、Retry、Timeline Command 和 Job 输出阶段重复校验。

## 12. 当前边界

尚未完成：

1. 可配置的部分成功继续策略；
2. `needs_review` 的确认与继续流程；
3. 已完成 Step 的自动补偿；
4. 外部 Provider 强制取消；
5. 500 节点压力、故障注入和生产数据库竞争基线；
6. 生成 Asset 的 Freshness 节点模型；
7. 更多故事生产链的自动依赖登记。

## 13. 验收证据

自动测试覆盖精确输入、传播、图约束、单点修复、Agent 输入、拓扑预览、数据库 claim、双协调器、崩溃恢复、Retry、Replan、迁移、工作台状态函数，以及完整后端/前端/lint/设计检查/生产构建。

## 14. 回滚

ArtifactVersion、Dependency、Provenance、Freshness、Plan、Step、Replan lineage 与 Operation 都是历史事实。代码回滚不会删除这些记录；内容恢复通过追加版本完成，不改写历史。
