# Artifact 级联修复预览

> 状态：只读预览、持久化执行、Retry 与 Replan 均已实现。  
> 日期：2026-08-12。  
> 执行契约见 `docs/regeneration-plan-execution.md`。

## 1. 目标

批量修复不能等同于“并行点击重新生成”。若 B 依赖 A、C 依赖 B，正确顺序必须是：

```text
A 可用 → 修复 B → 修复 C
```

预览先回答：

- 从哪些根 Artifact 开始；
- 是否包含当前下游；
- 当前版本依赖图的确定性拓扑顺序；
- 每一步采用什么动作；
- 哪些步骤可自动执行；
- 哪些步骤等待前驱、缺少替代素材、需要审阅或不可重放；
- 创建计划时需要冻结哪些目标版本。

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

最多接受和展开 500 个 Artifact。跨项目 Artifact 返回 404。遗留数据中若存在环，返回冲突，不猜测顺序。

## 3. 选择与拓扑

`include_downstream=true` 时，只沿“下游版本仍为当前版本”的依赖边扩展。历史 ArtifactVersion 的旧边不会混入计划。

拓扑只考虑本次选择内的边。选择外的上游列入 `external_upstream_artifact_ids`；若其 Freshness 不是 fresh，当前 Step 被阻塞，除非重新预览并把该上游纳入计划。

每个 Step 返回：

- `expected_current_version_id`；
- `depends_on`；
- `external_upstream_artifact_ids`；
- Freshness 与缺失输入；
- 动作、执行状态和结构化 blocker；
- `can_execute_automatically`；
- `available_after_plan`。

## 4. 动作分类

| 动作 | 语义 |
| --- | --- |
| `none` | 已是 fresh，不写入 |
| `regenerate_llm` | 具备可重放 Job 来源的 LLM Artifact |
| `recompile_timeline` | 使用当前上游与素材重新编译 Timeline |
| `repair_timeline_assets` | 需要为直接缺失 Asset 提供替代 |
| `review` | `needs_review`，等待人工判断 |
| `manual` | 当前没有安全自动动作 |

LLM 预览会验证 Provenance、来源 Operation、原 Job、Prompt、精确输入版本与素材。Timeline 缺失素材不会伪装成普通重编译。

## 5. 执行状态

| 状态 | 语义 |
| --- | --- |
| `ready` | 当前即可执行 |
| `waiting_for_predecessors` | 必须等待计划内前驱 |
| `requires_input` | 需要结构化素材替换输入 |
| `requires_review` | 需要人工审阅 |
| `manual` | 没有定义自动动作 |
| `blocked` | 锁定、来源不可重放、外部上游不新鲜或前驱不可解决 |
| `skipped` | 当前内容已经 fresh |

只有 `ready` 和 `waiting_for_predecessors` 的受支持动作计入 `automatable`。

## 6. 只读不变量

预览：

- 不通过 CommandBus；
- 不创建 OperationLog；
- 不创建 Job；
- 不改变 Freshness；
- 不追加 ArtifactVersion；
- 不修改 Plan 或目标状态。

自动测试在请求前后比较 Operation 数量，保证预览只读。

## 7. 从预览到计划

```http
POST /api/projects/{project_id}/artifact-regeneration/plans
```

创建时服务端重新计算预览并冻结快照。浏览器为一次创建意图提供稳定 `client_token`：失败重试重放同一 Plan，成功后的下一次意图使用新 token。

Plan / Step 保存拓扑、目标版本、动作、输入要求和 blocker。Start 再次检查目标版本，防止预览后的人工作业被旧计划覆盖。

## 8. Retry 与 Replan

- Retry 使用原 Plan 的拓扑与目标，只为失败 Step 创建新 attempt；
- Replan 使用原根选择重新读取当前图，原子终止旧意图并创建有 lineage 的新 Plan。

因此，目标版本或依赖图变化时不应强行 Retry；应使用 Replan。

## 9. 已验证不变量

测试覆盖：

- 三层依赖链拓扑顺序；
- 选择外 stale 上游阻塞；
- Timeline 缺失素材进入 `requires_input`；
- 跨项目选择不可读；
- 预览前后 OperationLog 不变；
- Plan 创建快照与 client token；
- Retry / Replan 与执行协调器的集成；
- 后端、前端、lint、设计检查和生产构建。

## 10. 当前边界

预览上限仍为 500 个节点；尚未完成大图压力和生产数据库遍历基线。`requires_review` 仍没有确认继续流程，生成 Asset 仍不是 Freshness 图节点。

## 11. 回滚

预览代码没有写入副作用。已经创建的 Plan、Step、lineage、Job、Operation 与 ArtifactVersion 是历史事实，不因代码回滚而删除。
