# M3：Dependency、Provenance、Freshness 与修复

> 状态：版本依赖、素材阻塞、单点修复和级联预览闭环已成立。  
> 日期：2026-08-12。  
> 本文只描述当前已经成立的系统不变量，并明确尚未实现的执行边界。

## 1. 目标

M3 回答五个可验证问题：

1. 一个产物究竟使用了哪些不可变 ArtifactVersion 与 Asset？
2. 上游前进或必需素材删除后，哪些当前产物已经不可信？
3. 用户在哪里看到状态、原因和后续影响？
4. 单个产物怎样安全修复并保持历史？
5. 多个受影响产物应按什么顺序修复，哪些步骤不能自动执行？

## 2. 数据模型

### 2.1 ArtifactDependency

依赖边连接精确上游版本与精确下游版本：

```text
upstream ArtifactVersion
        ↓
downstream ArtifactVersion
```

下游 Artifact ID 作为查询冗余字段保留。历史版本和历史边不可变，只有仍为当前版本的下游参与 Freshness 传播和级联预览。

### 2.2 AssetDependency

AssetDependency 连接一个不可变 Asset 输入与一个 ArtifactVersion。上游 Asset ID 不使用外键级联删除；边中保存必要快照，因此 Asset 删除后依赖仍作为 tombstone 存在，可以解释：

- 缺失的是哪个 Asset；
- 原名称、类型和 Unit 作用域；
- 哪个当前 ArtifactVersion 使用过它。

项目、下游 Artifact 和下游版本仍使用正常级联约束。

### 2.3 ArtifactProvenance

每个派生版本最多一条 Provenance，记录：

- 精确 `input_version_ids`；
- Provider 与 Model；
- Prompt version；
- 参数与 seed；
- Task attempt；
- 负责持久化的 Operation。

Provenance 用于审计，也用于判断旧产物是否具备安全重放路径。

### 2.4 ArtifactFreshness

| 状态 | 当前语义 |
| --- | --- |
| `fresh` | 当前版本没有已知失效输入 |
| `stale` | 上游 Artifact 已经前进，当前版本仍基于旧版本 |
| `blocked` | 必需 Asset 或上游 Artifact 输入缺失 / 阻塞 |
| `needs_review` | 状态已注册，但自动进入与人工确认策略尚未完成 |

## 3. 生产输入登记

### 3.1 LLM Artifact

LLM Job 输出通过同一 Artifact 持久化 Operation 登记输入、Provenance 和新版本。选择性重新生成会把旧输入 Artifact 替换为当前版本，并保留仍存在的 Asset 输入。

### 3.2 Agent 工具

Agent 的 `write_artifact` 和 `generate_media` 接受：

- `input_version_ids`；
- `input_artifact_ids`；
- `input_asset_ids`。

系统还会读取当前 Turn 的显式 `context_refs` 和项目 `pinned_refs`。Artifact 引用在首次提交事务中冻结为当前版本，跨项目引用失败。

Unit、项目、Bible 与普通 Prompt 文本不会自动展开成依赖。详见 `docs/agent-explicit-production-inputs.md`。

`write_artifact` 创建一等 Artifact / Asset 依赖和 Provenance。媒体 Job 将输入冻结进 Job payload，并保留在输出 Asset 的 generation 元数据中；当前 Asset 输出还不是 Freshness 图节点。

### 3.3 Timeline

Timeline 编译登记实际采用的 edit plan 版本，以及每个 clip 实际使用的 Asset。素材替换后会追加 Timeline 新版本并登记新的 AssetDependency，旧版本 tombstone 保留。

## 4. 状态传播

### 4.1 上游 Artifact 前进

上游追加新当前版本时：

1. 上游自身恢复为 `fresh`；
2. 查找使用其历史版本、且下游版本仍是当前版本的边；
3. 将这些下游标记为 `stale`；
4. 沿当前依赖图递归传播；
5. 历史下游版本保持不变。

### 4.2 Asset 删除

删除被当前 ArtifactVersion 使用的 Asset 时：

1. AssetDependency tombstone 保留；
2. 直接下游进入 `blocked`；
3. 缺失 Asset ID 沿 Artifact 依赖递归传播；
4. 项目 Freshness 查询返回可解释的 `blocked_by_asset_ids`；
5. 单元子树删除会在级联发生前先阻塞仍存活的外部下游。

### 4.3 图安全

登记 Artifact 依赖时拒绝：

- 同一 Artifact 的自依赖；
- 直接或间接依赖环；
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
```

项目 Freshness 默认只返回需要处理的 Artifact；`include_fresh=true` 返回全部状态。默认处理优先级：

```text
blocked → stale → needs_review → fresh
```

## 6. 工作台

顶栏内容状态中心、Artifact 面板和结构树共享项目 Freshness 查询：

- 顶栏显示需要处理的数量；
- 抽屉解释原因并可展开下游影响；
- Artifact 面板标记 `stale / blocked / needs_review`；
- `stale` 或 `blocked` 不能直接采用或锁定；
- 结构树按 Unit 聚合最严重状态并提供“需处理”筛选；
- 单个可重放 stale LLM Artifact 可以创建重新生成 Job。

Timeline 素材替换目前有后端显式操作；完整的工作台选择器仍属于后续产品层。

## 7. 单个 Artifact 修复

### 7.1 LLM 选择性重新生成

`POST /api/artifacts/{id}/regenerate` 只接受：

- Freshness 为 `stale`；
- 当前版本未锁定；
- 当前版本存在 Provenance；
- 来源 Operation 由持久化 LLM Job 创建；
- 原 Prompt 和 Job 仍存在；
- 上游 Artifact 当前都是 fresh；
- 必需 Asset 仍存在。

成功后保持 Artifact ID，只追加新版本；新版本登记刷新后的精确输入并恢复 fresh。

默认幂等键：

```text
artifact-regenerate:{artifact_id}:{expected_target_version_id}
```

持久化阶段再次检查目标版本，防止晚到模型结果越过人工修改。

### 7.2 Timeline 缺失素材修复

`POST /api/artifacts/{id}/repair-assets` 要求为当前版本每个直接缺失 Asset 提供兼容替代。系统验证项目、Unit 作用域和素材类型，然后重新编译 Timeline、追加新版本并登记新依赖。重复请求通过目标版本和替换映射指纹重放同一结果。

## 8. 级联修复预览

`POST /api/projects/{id}/artifact-regeneration/preview` 是只读查询。它从用户选择的根 Artifact 出发，可沿当前下游扩展，最多处理 500 个节点，并返回：

- 稳定拓扑顺序；
- 每一步冻结用的 expected current version；
- 内部前驱与选择外上游；
- `regenerate_llm / recompile_timeline / repair_timeline_assets / review / manual` 动作；
- `ready / waiting / requires_input / blocked` 等执行状态；
- 锁定、缺失 Provenance、来源不可重放、外部上游不新鲜和缺失素材等结构化 blocker。

预览不创建 Job、Operation 或版本，不改变 Freshness。详细契约见 `docs/regeneration-cascade-preview.md`。

## 9. 可观察性与幂等

- 所有写入通过 CommandBus / OperationLog；
- 上游变化和 Asset 删除导致的 Freshness 副作用合并进原 Operation 的 affected entities；
- 大 payload 只在业务表保存，OperationLog 使用指纹和稳定引用；
- Job 输出持久化按 Job / 槽位重放；
- Agent 工具按 turn / step 重放；
- 单点重新生成与 Timeline 修复均冻结目标当前版本。

## 10. 当前边界

尚未完成：

1. 级联预览的持久化 Plan / Step 与异步执行协调；
2. worker 重启后的级联计划恢复、部分失败和取消语义；
3. `needs_review` 的自动转换与人工确认流程；
4. 故事结构 → 剧本 → 镜头方案 → 分镜等更多生产链自动登记；
5. 将生成 Asset 建模为可传播 Freshness 的生产节点；
6. 500 节点预览的性能基线和数据库级游标遍历；
7. 工作台批量选择、素材替换输入和项目卡片摘要。

因此，不应把“可预览”描述成“已能可靠执行级联任务”，也不应把媒体 generation 元数据描述成完整 Asset 输出依赖图。

## 11. 验收证据

自动测试覆盖：

- 精确 ArtifactVersion / Asset 输入与 Provenance；
- 上游新版本触发 stale；
- Asset 删除和单元删除触发 blocked；
- tombstone 仍能解释缺失素材；
- 图自依赖、直接环、间接环和边数限制；
- 单个 LLM Artifact 重新生成及并发版本冲突；
- Timeline 素材替换、幂等与类型校验；
- Agent 直接、Turn 和 pinned 输入冻结；
- Agent 跨项目输入拒绝与步骤幂等；
- 级联预览拓扑、等待、外部阻塞、素材输入和只读性；
- 后端测试、前端测试、lint、设计检查与生产构建。

## 12. 回滚

查询与前端类型可独立回滚。已经持久化的 ArtifactVersion、Dependency、Provenance、Freshness 和 Operation 是历史事实，不应因代码回滚而删除。修复结果应通过版本恢复追加新版本，而不是改写历史。
