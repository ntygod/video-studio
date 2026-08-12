# Artifact 级联修复预览

> 状态：已实现只读预览；尚未实现持久化执行计划。  
> 日期：2026-08-12。

## 1. 目标

批量修复不能等同于“对一组 Artifact 并行点击重新生成”。若 B 依赖 A、C 依赖 B，正确顺序必须是：

```text
A 可用 → 修复 B → 修复 C
```

预览接口先回答以下问题，而不产生任何副作用：

- 从哪些根 Artifact 开始；
- 是否包含其当前下游；
- 当前版本依赖图的确定性拓扑顺序；
- 每一步可采用什么动作；
- 哪些步骤可以自动执行；
- 哪些步骤等待前驱、缺少替代素材、需要审阅或不可重放；
- 执行前需要冻结哪些目标版本。

## 2. API

```http
POST /api/projects/{project_id}/artifact-regeneration/preview
```

请求：

```json
{
  "artifact_ids": ["root-artifact-id"],
  "include_downstream": true
}
```

接口最多接受和展开 500 个 Artifact。跨项目 Artifact 返回 404。若遗留数据中存在依赖环，预览返回冲突而不是猜测执行顺序。

## 3. 选择与拓扑

`include_downstream=true` 时，系统只沿当前下游版本仍在使用的依赖边扩展。历史 ArtifactVersion 的旧边不会混入计划。

拓扑排序只考虑本次选择内的边。选择外的上游会以 external upstream 形式列出；若其 Freshness 不是 `fresh`，当前步骤被阻塞，除非用户重新预览并把该上游纳入计划。

响应中的 `order` 是稳定执行顺序，每个 step 同时包含：

- `expected_current_version_id`；
- `depends_on`；
- `external_upstream_artifact_ids`；
- Freshness 与缺失输入；
- 建议动作、状态和结构化 blocker；
- `can_execute_automatically`；
- `available_after_plan`。

## 4. 动作分类

| 动作 | 语义 |
| --- | --- |
| `none` | Artifact 已是 fresh，不需要写入 |
| `regenerate_llm` | 具备可重放 Job 来源的 LLM Artifact |
| `recompile_timeline` | Timeline 可以用当前上游和素材重新编译 |
| `repair_timeline_assets` | 当前 Timeline 直接缺少素材，需要逐一提供替代 Asset |
| `review` | `needs_review`，需要人工判断 |
| `manual` | 当前没有安全自动动作 |

LLM 预览会验证当前版本 Provenance、来源 Operation、原 Job、Prompt、精确输入版本和素材是否仍可读。Timeline 缺失素材不会伪装成普通重新编译，而是明确进入替换素材流程。

## 5. 执行状态

| 状态 | 语义 |
| --- | --- |
| `ready` | 当前即可执行 |
| `waiting_for_predecessors` | 前驱在本计划内且可修复，必须等待 |
| `requires_input` | 需要用户提供素材替换等结构化输入 |
| `requires_review` | 需要人工审阅 |
| `manual` | 没有定义自动修复动作 |
| `blocked` | 锁定、来源不可重放、外部上游不新鲜或前驱不可解决 |
| `skipped` | 当前内容已经 fresh |

只有 `ready` 和 `waiting_for_predecessors` 的受支持动作计入 `automatable`。

## 6. 只读不变量

预览服务：

- 不通过 CommandBus；
- 不创建 OperationLog；
- 不创建 Job；
- 不改变 Freshness；
- 不追加 ArtifactVersion；
- 不修改目标状态。

自动测试在请求前后比较项目 Operation 数量，确保预览保持只读。

## 7. 为什么暂不直接执行

一个安全的执行层还必须具备：

1. 持久化 Plan 与 Step；
2. 冻结每个目标的 expected version；
3. 为每一步分配独立幂等键；
4. 异步任务完成后再释放后继步骤；
5. 上游失败时确定性跳过或阻塞下游；
6. 进程重启后恢复协调器；
7. 用户输入与替换映射的持久化审计；
8. 部分失败、取消和重新规划语义。

在这些不变量成立前，接口只提供预览，不会在 HTTP 请求中同步串行调用多个外部 Provider，也不会创建会占满 worker 的父任务等待子任务。

## 8. 验收覆盖

自动测试覆盖：

- 三层依赖链的下游扩展与拓扑顺序；
- 上游 fresh、首个下游 ready、后续下游等待前驱；
- 未选择的 stale 上游阻塞当前步骤；
- 缺失 Timeline Asset 进入 `requires_input`；
- 跨项目选择不可读；
- 预览前后 OperationLog 数量不变；
- 后端、前端测试、lint、设计检查与生产构建。

## 9. 回滚

预览 API 与前端类型没有持久化数据，可直接回滚。回滚不会影响现有 Artifact、Freshness、Job 或 Operation。
