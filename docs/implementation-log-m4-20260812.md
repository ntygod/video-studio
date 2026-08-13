# M4 实施记录 · 2026-08-13

> 分支：`refactor/kernel-v2-foundation`。  
> 当前阶段：M4.1 至 M4.6 Agent 生产治理与成本闭环。

## M4.1 通用运行时

`0010` 新增 RuntimePlan、RuntimeTask、RuntimeTaskAttempt 与 RuntimeTaskEvent，完成 DAG、claim、lease、heartbeat、checkpoint、Attempt、timeout、retry、Cancel、恢复和事件续读。

## M4.2 Agent Turn

Turn、消息、Plan 与 Task 原子提交；startup 自动恢复。Agent 冻结 Provider/Model和 tool-loop checkpoint，logical tool call 与 Command 幂等身份跨 Attempt 稳定。RuntimeTaskEvent 驱动 SSE 与终态修复。

## M4.3 准入与事件身份

`0011` 增加数据库 admission slot 与 semantic event dedupe。Agent 容量满时 429 并完整回滚 Turn；重放事件返回原 ID 与 seq。

## M4.4 PolicyDecision 与硬预算

`0012` 增加 PolicyDecision、Budget Ledger、Task Usage 水位与 exactly-once Consumption。高风险工具副作用前 suspend，批准/拒绝后从 checkpoint 恢复。token、tool 与 wall-clock 预算进入执行状态机。

## M4.5 审批工作台与 TTL

项目级审批中心、当前 Turn 审批卡与刷新恢复完成。`0013` 增加 `expires_at`，startup / reaper 回收无人处理审批；用户审批与过期通过 CAS 决定唯一终态。

## M4.6 Provider 价格与成本

`0014` 新增：

- `model_pricing_profiles`；
- `runtime_cost_entries`；
- Agent 默认 10 USD 成本预算。

LLM 模型价格规范化为整数微美元。Agent 在真实请求前把 Provider、Model 与价格冻结进 checkpoint。OpenAI streaming 与 JSON protocol Adapter 传递 usage、response ID 和实际 model ID。

每个 usage 生成不可变 CostEntry，并在同一事务中推进 Task 水位和 Plan Ledger。稳定 `usage_key` 防止重复计费；改价不改变历史快照。

到达上限时下一次请求前拒绝；响应跨预算时先保存真实费用，再失败关闭。缺少价格或 usage 的调用保留审计并标记未完整计价。

工作台新增：

- 模型输入/输出/缓存/请求价格编辑；
- 渠道价格覆盖提示；
- 模型能力价格列；
- Agent Turn USD、token、调用次数和上限；
- 未定价与超限告警；
- 费用明细。

## 自动验收

新增或扩展覆盖：

- Decimal 价格规范化与 cached token 计算；
- 缺少 usage 不伪装完整计价；
- Provider 价格 API；
- 价格快照跨改价稳定；
- CostEntry exactly-once；
- Ledger token/cost 去重；
- 未定价调用审计；
- 请求前成本门限；
- 请求后跨预算费用不回滚；
- `0014` 迁移与唯一约束；
- 前端 USD ↔ 微单位往返和 UI 类型语法检查。

## 当前边界

- 外部 Provider 请求尚无通用 idempotency 与账单对账；
- 媒体/TTS/渲染/存储成本尚未计量；
- 未定价调用只告警，不构成严格金额上限；
- 角色审批、Planner/Reviewer、通用 Replan/compensation、token 持久流和 PostgreSQL 故障基线尚未完成。

## 回滚

价格配置可以回滚，CostEntry、Ledger、Decision、Event、Operation 与业务版本是历史事实，不应删除或重算。
