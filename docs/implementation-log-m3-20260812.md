# M3 扩展实施记录 · 2026-08-12

> 对应分支：`refactor/kernel-v2-foundation`。  
> 本记录是 `docs/implementation-log.md` 的 M3 后续施工补充。

## 1. Agent 显式生产输入

- 新增统一解析器，把工具直接输入、当前 Turn `context_refs` 和项目 `pinned_refs` 解析为精确 ArtifactVersion / Asset ID。
- Artifact 引用只在首次提交事务中读取 current pointer，随后冻结进 Job 或 Artifact 依赖。
- Unit、项目、Bible 和自然语言不展开成隐藏依赖。
- Agent `write_artifact` 通过 CreateArtifactCommand 在同一事务中创建版本、ArtifactDependency、AssetDependency 与 Provenance。
- Agent `generate_media` 把精确输入冻结进 Job payload；Provider 媒体和 TTS 输出把输入 ID 保留在 Asset generation 元数据。
- 工具 schema 对模型暴露 `input_version_ids / input_artifact_ids / input_asset_ids`。
- 跨项目输入失败，不创建 Job 或 Artifact。

## 2. 图与 Asset 阻塞闭环

- Alembic head `20260811_0005` 增加 `asset_dependencies`。
- Asset 删除后边以快照 tombstone 保留，直接下游和当前 Artifact 下游递归进入 blocked。
- 单元子树删除先计算仍存活的外部下游，再让数据库级联删除内部 Artifact 与 Asset。
- Freshness 副作用并入触发删除 / 版本推进的 OperationLog affected entities。
- Artifact 图拒绝自依赖、直接 / 间接环、跨项目边和超过安全上限的输入。

## 3. 修复操作

- stale LLM Artifact 继续使用来源 Job 重放，保持 Artifact ID 并只追加版本。
- LLM 重放保留当前 Asset 输入，并对目标版本使用乐观锁。
- Timeline 缺失素材修复要求完整替换映射，校验项目、Unit 作用域和兼容类型；成功后追加版本并登记新 Asset 边。

## 4. 级联预览

- 新增 `/api/projects/{id}/artifact-regeneration/preview`。
- 只沿当前下游版本使用的边扩展，最多 500 个 Artifact。
- 使用确定性拓扑排序，区分内部前驱与选择外上游。
- 对每一步输出 expected version、建议动作、状态、blocker、自动执行能力和计划后可用性。
- 检查 LLM 来源 Job、Prompt、Provenance、锁定状态、缺失版本、缺失素材与外部 stale / blocked 上游。
- 预览不进入 CommandBus；回归测试确认 OperationLog 数量不变。
- 前端 API 层增加完整类型和 mutation hook，但尚未提供批量执行 UI。

## 5. 验证

分支 CI 顺序执行：

1. 全部后端测试；
2. 前端 Node 测试；
3. ESLint；
4. 设计与令牌检查；
5. Next.js 生产构建。

新增回归覆盖显式输入合并、Agent 幂等、跨项目拒绝、Artifact / Asset 依赖登记、三层级联拓扑、选择外上游阻塞、Timeline 替换输入和预览只读性。

## 6. 明确保留的边界

- 级联执行还没有持久化 Plan / Step，也没有可恢复协调器。
- 不能用一个占据 worker 的父 Job 同步等待子 Job；执行层必须释放 worker，并在子任务终态后恢复调度。
- 媒体输出 Asset 只保留输入审计元数据，尚未成为 Freshness 图节点。
- `needs_review` 仍没有自动进入和确认策略。
- 更多故事生产链需要在各自持久化 Operation 中显式登记依赖。

## 7. 回滚

Agent 输入解析、预览服务和前端契约均可独立回滚。数据库中的版本、依赖、Provenance 和 Operation 保持不变；这些记录描述已经发生的历史事实。
