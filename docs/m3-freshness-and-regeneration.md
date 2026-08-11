# M3：Artifact Freshness 与选择性重新生成

> 状态：已在 `refactor/kernel-v2-foundation` 实现首个可用闭环。  
> 日期：2026-08-11。  
> 本文描述当前已经成立的系统不变量，也明确尚未实现的边界。

## 1. 目标

M3 要解决的不是“再放一个重新生成按钮”，而是回答四个可验证问题：

1. 一个派生产物究竟使用了哪些**精确输入版本**？
2. 上游发生变化后，哪些当前产物已经不再可信？
3. 用户在哪里能看到原因和后续影响？
4. 重新生成时，如何确保只更新目标产物、采用最新输入，并且不会重复创建 Job 或 Artifact？

当前闭环覆盖版本级 Artifact 依赖、生成来源、`stale` 传播、工作台状态展示、影响查询，以及有完整来源记录的 LLM Artifact 选择性重新生成。

## 2. 数据模型

### 2.1 ArtifactDependency

一条依赖边连接：

```text
upstream ArtifactVersion
        ↓
downstream ArtifactVersion
```

依赖以不可变版本 ID 为端点，而不是只记录 Artifact ID。这样系统能够区分“由剧本 v2 生成”和“由剧本当前版本生成”这两个完全不同的事实。

当前字段包括：

- `project_id`
- `upstream_version_id`
- `downstream_artifact_id`
- `downstream_version_id`
- `dependency_type`
- `metadata_json`

### 2.2 ArtifactProvenance

每个派生版本最多有一条来源记录，包含：

- 精确 `input_version_ids`
- Provider 与 Model
- Prompt 版本
- 参数与 seed
- Task attempt
- 负责持久化的 Operation

它用于审计，也用于判断一个旧产物是否具备可安全重放的生成路径。

### 2.3 ArtifactFreshness

Freshness 是 Artifact 当前版本的可操作状态：

| 状态 | 当前语义 |
| --- | --- |
| `fresh` | 当前版本由仍然有效的输入产生，或尚无证据表明它已失效 |
| `stale` | 上游 Artifact 已经前进，当前版本仍基于旧输入 |
| `blocked` | 预留给必需输入缺失或已阻塞的情况；目前尚未形成完整的 Asset 自动传播闭环 |
| `needs_review` | 已注册但尚未定义自动进入策略，暂不由生产流程主动设置 |

## 3. 当前状态转换

### 3.1 上游追加新版本

当一个 Artifact 追加并切换到新当前版本时：

1. 该 Artifact 自身恢复为 `fresh`；
2. 系统查找所有使用其历史版本、且下游版本仍是当前版本的依赖边；
3. 将这些下游标记为 `stale`；
4. 继续向更下游递归传播。

历史下游版本不会被修改。只有仍在使用的当前版本参与传播。

### 3.2 登记派生关系

新产物登记依赖时：

- 输入都是当前且 `fresh`：输出为 `fresh`；
- 输入版本已经不是上游当前版本：输出为 `stale`；
- 上游 Freshness 已是 `blocked`：输出可继承为 `blocked`。

当前尚未实现一等的 `Asset → ArtifactVersion` 依赖边，因此“删除必需 Asset 后自动把下游置为 blocked”还不是完整系统能力。时间线目前会把 `asset_ids` 记录在 provenance 参数和依赖 metadata 中，用于审计，但不能替代一等依赖关系。

## 4. 查询 API

当前公开查询包括：

```http
GET /api/artifact-versions/{version_id}/provenance
GET /api/artifacts/{artifact_id}/freshness
GET /api/artifacts/{artifact_id}/dependencies
GET /api/artifacts/{artifact_id}/impact
GET /api/projects/{project_id}/artifact-freshness
```

项目级接口默认只返回需要处理的 Artifact，并同时返回四种状态计数。传入：

```http
?include_fresh=true
```

可取得项目全部 Artifact 状态。

默认处理顺序为：

```text
blocked → stale → needs_review → fresh
```

## 5. 工作台展示

### 5.1 顶栏内容状态中心

存在需要处理的内容时，工作台顶栏显示数量入口。抽屉中提供：

- 状态与可读原因；
- 发生变化的输入版本数量；
- 当前 Artifact 的版本入口；
- 可展开的后续影响范围；
- 对合格 `stale` Artifact 的选择性重新生成动作。

没有可处理内容时入口自动隐藏。查询失败会显示明确错误和重试入口。

### 5.2 Artifact 面板

Artifact 切换卡和当前内容区会显示 `已过期 / 已阻塞 / 待审阅`。

`stale` 或 `blocked` 内容不能直接“采用版本”或“定稿”，避免把已知失效结果提升为正式状态。用户仍可查看源码和版本历史。

### 5.3 结构树

结构树按 Unit 聚合最严重状态和需要处理的 Artifact 数量，并提供“需处理”筛选。父节点在过滤时保留，以维持可理解的上下文路径。

## 6. 选择性重新生成

接口：

```http
POST /api/artifacts/{artifact_id}/regenerate
```

当前只支持具备完整来源记录的 `stale` LLM Artifact。

### 6.1 资格条件

必须同时满足：

1. Artifact 当前状态是 `stale`；
2. 当前版本未 `locked`；
3. 当前版本存在 Provenance；
4. Provenance 中的 Operation 来自一个持久化 Job；
5. 原始 Job 是可重放的 LLM 生成任务；
6. 原始 Prompt 仍然存在；
7. 所有上游 Artifact 仍存在，且其当前状态都是 `fresh`；
8. 目标 Artifact 从请求到结果落库期间没有被其他操作改写。

不满足条件时，接口返回明确的 `409` 或 `422`，不会猜测 Prompt，也不会创建一个身份不明的新 Artifact。

### 6.2 输入刷新

系统从旧 Provenance 读取原始输入 Artifact，然后把每个输入替换为它的**当前版本**。新的 Job payload 中包含：

- 最新 `input_version_ids`；
- `context.current_inputs` 中的当前输入 payload；
- 原始 Prompt 与参数；
- 明确的重新生成约束；
- `target_artifact_id`；
- 请求时的 `expected_target_version_id`。

旧 context 只作为补充。若它与 `current_inputs` 冲突，生成约束要求模型以当前输入为准。

### 6.3 写入不变量

重新生成成功后：

- Artifact ID 不变；
- 只追加一个新版本，不覆盖历史；
- 新版本记录新的精确输入、Provider、Model、Prompt 版本、参数、Attempt 和 Operation；
- 输入有效时目标恢复为 `fresh`；
- 下游仍可根据目标新版本继续传播 Freshness。

### 6.4 幂等与并发保护

同一目标当前版本的默认业务幂等键为：

```text
artifact-regenerate:{artifact_id}:{expected_target_version_id}
```

因此重复点击或重复 HTTP 请求会返回同一个 Job，而不是创建重复任务。

Job 输出持久化还有第二层幂等：`generated_artifact_attempt` 会查找该 Job 已成功提交的 Artifact Operation。即使进程在 Artifact 事务提交后、Job result 更新前退出，重试也会重放已提交结果，而不是再次调用模型或追加第二个版本。

写入前再次检查 `expected_target_version_id`。若用户在生成期间手工修改了目标，Job 会以冲突失败，绝不会把较晚的模型结果覆盖到新的人工版本之后。

## 7. 失败与恢复

| 场景 | 行为 |
| --- | --- |
| Provider / LLM 调用失败 | Job 失败，不创建目标新版本 |
| 输入 Artifact 已删除 | 拒绝创建重新生成 Job |
| 输入本身 stale / blocked | 拒绝，要求先修复上游 |
| 目标在执行期间发生变化 | 持久化阶段冲突失败 |
| 重复请求 | 重放同一个 Job |
| Artifact 已提交但 Job result 未更新 | 重放已成功的 Artifact Operation |
| 持久化事务失败 | 数据库回滚，不留下半条版本或来源关系 |

## 8. 可观察性

重新生成由两条持久化记录共同描述：

- `job`：外部执行状态、进度、错误和事件；
- `operation_log`：创建 Job 与持久化 Artifact 版本的参数指纹、前置条件、影响实体和结果引用。

大型 payload 不复制进 OperationLog，只保存稳定指纹和可重放引用。

## 9. 当前边界与下一步

以下能力明确尚未完成：

1. 一等的 `Asset → ArtifactVersion` 依赖表和删除后的 `blocked` 递归传播；
2. 缺失素材的替换、解除阻塞和重新编译操作；
3. `needs_review` 的自动转换策略和人工确认流程；
4. 多个下游 Artifact 的选择性批量 / 级联重新生成；
5. 故事结构 → 剧本 → 镜头方案 → 分镜等更多生产链的自动依赖登记；
6. 依赖环检测；
7. 图规模限制、数据库级游标遍历和大型项目性能基线；
8. 项目库卡片上的状态摘要。

在这些能力完成前，不应把 timeline metadata 中的 `asset_ids` 描述成完整 Asset 依赖图，也不应把 `blocked` 或 `needs_review` 宣传为已经自动覆盖所有生产流程。

## 10. 验收证据

当前自动验证覆盖：

- 项目 Freshness 聚合与 actionable 默认过滤；
- 上游新版本触发 `stale`；
- 状态排序和 Unit 聚合；
- 精确输入刷新；
- 同一 Artifact 追加版本；
- 重新生成后恢复 `fresh`；
- 目标并发改写冲突；
- 缺少可重放来源时拒绝；
- 同一目标版本重复请求只创建一个 Job 和一个 Operation；
- 后端测试、前端测试、lint、设计检查和生产构建。

## 11. 回滚说明

本阶段新增的 UI 和查询 API 可以独立回滚，不会破坏已有 Artifact 数据。

选择性重新生成只通过现有 CommandBus / Job 路径追加版本；回滚代码不会删除已经成功生成的版本。若需要撤销某次结果，应使用 Artifact 版本恢复机制追加一个恢复版本，而不是改写历史。
