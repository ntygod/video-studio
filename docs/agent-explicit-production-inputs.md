# Agent 显式生产输入

> 状态：已实现。  
> 日期：2026-08-12。  
> 适用范围：Agent 的 `write_artifact` 与 `generate_media` 生产工具。

## 1. 问题

Agent 可以在提示上下文里看到很多内容，但“模型看过某段文字”并不等于“系统可以把它登记为生产依赖”。如果依据 Prompt 文本猜输入，会产生三个不可接受的问题：

1. 同一请求重试时，Artifact 的当前版本可能已经变化；
2. 引用一个 Unit 可能在不同时间展开成不同数量的稿件与素材；
3. 系统无法证明一个输出究竟使用了哪些不可变输入。

因此，生产依赖只来自结构化、可验证的显式引用。

## 2. 输入来源与顺序

提交生产动作时，系统按以下顺序解析输入，并保持第一次出现的顺序去重：

1. 工具参数中的 `input_version_ids`；
2. 工具参数中的 `input_artifact_ids`，在提交事务中冻结为其当前版本；
3. 工具参数中的 `input_asset_ids`；
4. 当前 Agent Turn 的 `context_refs`；
5. 项目设置中的 `pinned_refs`。

支持的引用类型包括：

- `artifact` / `artifact_current`；
- `artifact_version` / `artifact-version` / `version`；
- `asset` / `media_asset` / `media-asset`。

所有实体必须属于当前项目。跨项目引用按不可读实体处理，生产动作失败且不会留下 Job 或 Artifact。

## 3. 明确不展开的引用

以下引用可以进入 Prompt 上下文，但不会自动成为生产依赖：

- Unit；
- 整个项目；
- Bible 片段；
- 普通对话文字；
- 从自然语言中推断出的名称或路径。

特别是 Unit 引用不会展开成“当时该 Unit 下面所有 Artifact 与 Asset”。这条规则保证依赖集合不会随项目内容增长而漂移。

## 4. `write_artifact`

Agent 直接写入 Artifact 时：

1. CommandBus 在同一数据库事务中解析显式输入；
2. 创建 Artifact 与首个 ArtifactVersion；
3. 登记版本级 ArtifactDependency；
4. 登记 AssetDependency；
5. 写入包含 Operation 与 Agent Turn 的 Provenance；
6. 以 `agent:{turn_id}:{step_id}` 保证工具步骤幂等。

相同步骤重放只返回原 Artifact 和 Operation。即使上游 Artifact 此后已经前进，旧输出仍然保留当时冻结的版本 ID，并由 Freshness 传播正确进入 `stale`。

Agent 直接写稿目前不是可重放的 LLM Job，因此它拥有完整的依赖与审计记录，但不会被单 Artifact 的 `/regenerate` 接口自动重放。需要重新生成时应由后续持久化计划显式定义动作。

## 5. `generate_media`

Agent 创建媒体任务时，精确输入先冻结进 Job payload。Provider 图片、视频和 TTS 输出还会把这些 ID 保留在 Asset 的 `generation` 元数据中，供审计与后续生产链使用。

当前图模型的 Freshness 节点是 Artifact，而不是 Asset 输出。因此：

- 可以证明媒体 Job 使用了哪些 ArtifactVersion 与 Asset；
- 不能据此宣称生成媒体本身会自动进入 `stale / blocked`；
- 若要让媒体输出参与完整传播，需要后续引入 Asset 派生图或统一生产节点模型。

## 6. 幂等语义

输入解析发生在第一次 Command 执行的事务内，结果随 Job 或 Artifact 一起持久化。相同 Agent step 重放时返回原结果，不会重新解释当前 Artifact 指针或后来修改的 `pinned_refs`。

追踪字段，如 `_request_id`，不参与 Job 的业务 payload 指纹，因此请求链路变化不会破坏业务幂等。

## 7. 验收覆盖

自动测试覆盖：

- 工具直接输入、Turn 引用和 pinned 引用的稳定合并；
- Artifact 引用冻结为精确当前版本；
- Unit 引用不产生隐藏依赖；
- Agent 写稿登记 Artifact 与 Asset 输入；
- 上游前进后原输入版本保持不变；
- 相同步骤只创建一个 Job 或 Artifact；
- 跨项目引用失败且不留下生产实体；
- Agent 工具 schema 对模型暴露三种显式输入字段。

## 8. 回滚

解析器和 Agent 工具字段可以独立回滚。已经写入的依赖、Provenance 和 Job payload 是历史事实，不应被删除；回滚只影响后续生产动作如何登记输入。
