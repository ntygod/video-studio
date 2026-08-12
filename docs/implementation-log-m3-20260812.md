# M3 扩展实施记录 · 2026-08-12

> 对应分支：`refactor/kernel-v2-foundation`。  
> 本记录是 `docs/implementation-log.md` 的 M3 后续施工补充。

## 1. Agent 显式生产输入

- 统一解析工具直接输入、Turn `context_refs` 与项目 `pinned_refs`；
- Artifact 引用在首次提交事务中冻结为精确版本；
- Unit、项目、Bible 和自然语言不展开为隐藏依赖；
- `write_artifact` 同事务创建版本、ArtifactDependency、AssetDependency 与 Provenance；
- `generate_media` 把精确输入写入 Job，并保留到输出 Asset metadata；
- 工具 schema 暴露 `input_version_ids / input_artifact_ids / input_asset_ids`；
- 跨项目输入失败且不创建生产实体。

## 2. Artifact / Asset 图与传播

- `20260811_0005` 增加 AssetDependency；
- Asset 删除后 tombstone 保留；
- Artifact 前进递归传播 stale；
- Asset / 单元删除递归传播 blocked；
- 图拒绝自依赖、环、跨项目边与超限输入；
- Freshness 副作用进入原 Operation 的 affected entities。

## 3. 单点修复

- stale LLM Artifact 使用来源 Job 重放，保持 Artifact ID并追加版本；
- 重放保留当前 Asset 输入并检查目标版本；
- Timeline 缺失素材使用完整兼容替换映射；
- stale Timeline 使用独立重编译 Command。

## 4. 级联预览

- 新增项目级只读预览；
- 只沿当前下游版本扩展，最多 500 个 Artifact；
- 使用确定性拓扑排序；
- 返回 expected version、动作、前驱、外部上游、blocker 与自动执行能力；
- 验证 LLM 来源、Prompt、Provenance、锁定、缺失版本和素材；
- 测试确认预览不创建 Operation、Job 或版本。

## 5. 持久化 Plan / Step

`20260812_0006` 新增：

- `regeneration_plans`；
- `regeneration_plan_steps`。

Plan 保存根选择、快照、状态和摘要；Step 冻结目标版本、拓扑、动作、输入、Job 与结果。创建计划时服务端重新预览并校验快照。

## 6. 可恢复协调器

- Start 再次验证所有目标版本；
- LLM Step 创建持久化 Job 后立即返回；
- Timeline Step 执行本地幂等 Command；
- 每个 Step 使用确定性 Operation key；
- Job 回调、启动恢复和周期 reaper 推进 Plan；
- 覆盖 Job 已创建未补链、输出已提交未更新 Job、回调丢失等崩溃窗口；
- Cancel 合作式停止未完成 Job，不回滚成功版本。

## 7. 数据库级 Step claim

`20260812_0007` 新增：

- `claim_token`；
- `claim_owner`；
- `claim_until`；
- `claim_attempt`；
- claimable 索引。

协调器使用数据库 CAS 抢占 Step。测试验证：

- 双协调器只有一个 winner；
- 只创建一个 Job；
- 租约过期可接管；
- Cancel 清除 claim；
- 迟到 owner 不能完成；
- 终态 Plan 不会被旧协调器复活。

## 8. Retry attempt

`20260812_0008` 新增 Plan / Step `execution_attempt` 与 Step `attempt_history_json`。

- Retry 只接受 settled failed Plan；
- 只重置失败 Step；
- 保留旧 Job、输入、结果、blocker、错误和时间；
- 新 attempt 使用新的 Operation key；
- Job payload 带 Step attempt；
- 旧 Job 回调不能覆盖新 attempt；
- 目标版本漂移拒绝 Retry；
- 相同 expected attempt 的网络重放不重复递增。

工作台显示执行次数、历史失败和“重试失败步骤”。

## 9. Replan lineage

`20260812_0009` 新增 `regeneration_plan_replans`。

- 从旧 Plan 根选择重新读取当前图；
- 允许 draft / blocked / failed / canceled source；
- 活动 Job 或 claim 存在时拒绝；
- 在同一事务中终止旧意图并创建新 draft；
- source 与 target 各自唯一，形成线性 lineage；
- 稳定 client token 支持网络重放；
- Replan 与旧 Start/Retry 竞争时由状态 CAS 决定唯一胜者。

工作台支持按当前图重新规划、打开后续计划和返回来源计划。

## 10. 工作台

内容状态中心当前支持：

- Freshness 原因与影响；
- 单项修复与级联预览；
- Plan 创建、Start、Cancel；
- 缺失素材输入；
- 运行轮询与历史重开；
- Retry attempt history；
- Replan lineage 导航。

界面明确区分 Retry 与 Replan，避免把目标漂移误当作普通任务失败。

## 11. 自动验证

分支 CI 顺序执行：

1. 全部后端测试；
2. 前端 Node 测试；
3. ESLint；
4. 设计与令牌检查；
5. Next.js 生产构建。

新增回归覆盖：精确输入、Agent 幂等、传播、图约束、拓扑预览、迁移、双协调器、claim 接管、取消竞态、崩溃恢复、Retry、旧 Job 隔离、Replan 当前图、唯一 lineage、原子退休 source 与工作台状态函数。

## 12. 当前边界

- 尚无可配置的部分成功继续策略；
- `needs_review` 尚无确认继续接口；
- 已完成 Step 不自动补偿；
- 外部 Provider 仍是合作式取消；
- 500 节点压力、故障注入和生产数据库竞争基线待建立；
- 生成 Asset 尚未成为 Freshness 节点；
- 更多故事生产链仍需逐个接入依赖登记。

## 13. 回滚

解析器、协调器、Retry、Replan 与前端界面可独立回滚。数据库中的版本、依赖、Provenance、Plan、Step、lineage 与 Operation 保持不变，因为它们描述已经发生的历史事实。
