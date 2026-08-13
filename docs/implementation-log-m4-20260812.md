# M4 实施记录 · 2026-08-13

> 分支：`refactor/kernel-v2-foundation`。  
> 当前阶段：M4.1 至 M4.7 Agent 生产治理、成本与严格合规闭环。

## M4.1 通用运行时

`0010` 新增 RuntimePlan、RuntimeTask、RuntimeTaskAttempt 与 RuntimeTaskEvent，完成 DAG、claim、lease、heartbeat、checkpoint、Attempt、timeout、retry、Cancel、恢复和事件续读。

## M4.2 Agent Turn

Turn、消息、Plan 与 Task 原子提交；startup 自动恢复。Agent 冻结 Provider/Model与 tool-loop checkpoint，logical tool call 与 Command 幂等身份跨 Attempt 稳定。RuntimeTaskEvent 驱动 SSE 与终态修复。

## M4.3 准入与事件身份

`0011` 增加数据库 admission slot 与 semantic event dedupe。Agent 容量满时 429 并完整回滚 Turn；重放事件返回原 ID 与 seq。

## M4.4 PolicyDecision 与硬预算

`0012` 增加 PolicyDecision、Budget Ledger、Task Usage 水位与 exactly-once Consumption。高风险工具副作用前 suspend，批准/拒绝后从 checkpoint 恢复。token、tool 与 wall-clock 预算进入执行状态机。

## M4.5 审批工作台与 TTL

项目级审批中心、当前 Turn 审批卡与刷新恢复完成。`0013` 增加 `expires_at`，startup/reaper 回收无人处理审批；用户审批与过期由 CAS 决定唯一终态。

## M4.6 Provider 价格与成本

`0014` 新增 `model_pricing_profiles`、`runtime_cost_entries` 和默认 10 USD Agent 预算。LLM 价格规范化为整数微美元，真实请求前冻结 Provider/Model/价格，usage 生成不可变 CostEntry 并 exactly-once 推进 Ledger。

到达上限时请求前拒绝；响应跨预算时先保存真实费用。缺少价格或 usage 的调用保留 `priced=false` 审计。工作台支持价格编辑、Turn 成本摘要、告警和明细。

## M4.7 项目严格 Provider 成本策略

ProjectSettings 新增：

```json
{
  "runtime_cost_policy": {
    "unpriced_provider_mode": "allow"
  }
}
```

默认 allow 保持兼容。每个新 Agent RuntimePlan 把项目策略冻结到 `policy.provider_cost_policy`；项目后续改动不影响运行中 Plan。

block 模式建立两个 fail-closed 边界：

- 模型无显式价格时，在 Provider 请求前写 `runtime.cost_policy.blocked` 并失败；
- 已配置 token 价格但响应无 usage 时，先提交 unpriced CostEntry，再写阻断事件并失败。

策略阻断复用硬预算终止控制流，不进入普通异常重试。项目策略更新通过 PatchProjectCommand、revision 乐观锁和 OperationLog。

工作台顶栏新增成本策略中心，解释尽力/严格语义、策略冻结和显式 0 价格要求。

## 自动验收

覆盖：

- 价格、usage、CostEntry 与 Ledger；
- 项目策略读写和 revision；
- 新 Plan 冻结、旧 Plan 不漂移；
- 严格预检不调用 Provider；
- 响应缺 usage 时费用事实不回滚；
- allow 模式保持 unpriced 审计；
- 阻断事件 exactly-once；
- 前端 helper、类型、lint、设计检查和生产构建。

## 当前边界

- 外部 Provider 请求无通用 idempotency 与账单对账；
- 媒体/TTS/渲染/存储成本尚未计量；
- 角色审批、Planner/Reviewer、通用 Replan/compensation、token 持久流和 PostgreSQL 故障基线尚未完成；
- 严格策略尚无按 Provider/Model/角色的细粒度覆盖。

## 回滚

价格和项目策略可以回滚；CostEntry、Ledger、Decision、Event、Operation 与业务版本是历史事实，不应删除或重算。
