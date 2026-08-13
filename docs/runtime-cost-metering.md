# Runtime Provider 成本计量

> 状态：Agent LLM 调用的价格快照、不可变费用明细与硬成本预算已实现。  
> 日期：2026-08-13。  
> Alembic revision：`20260812_0014`。

## 1. 目标

Runtime 以前已经保存 token、工具次数和 `cost_microunits` 字段，但成本没有可信来源。本阶段建立以下可验证链路：

```text
ModelProfile 定价
  → Agent checkpoint 冻结价格
  → Provider 返回 usage
  → RuntimeCostEntry
  → Plan / Task Budget Ledger
  → 成本预算判断与工作台展示
```

系统必须同时保证：

1. 改价不重写历史调用；
2. 同一 usage 事件重放不重复计费；
3. Provider 已经发生的费用不能因预算异常而回滚；
4. 到达预算上限后，下一次 Provider 调用在发出 HTTP 请求前被拒绝；
5. 缺少价格或 usage 时明确标记为未完整计价，不伪造零成本。

## 2. 价格表示

当前只支持 USD。持久化使用整数微美元，避免浮点累积：

```text
1 USD = 1,000,000 microunits
```

LLM 模型可配置：

```json
{
  "currency": "USD",
  "input_microunits_per_million_tokens": 1250000,
  "output_microunits_per_million_tokens": 5000000,
  "cached_input_microunits_per_million_tokens": 250000,
  "request_microunits": 10
}
```

API 和工作台接受人类可读的 USD 数值，并在写入边界立即规范化为整数。负数、非有限值和非整数微单位会被拒绝。

当前 token 价格只用于 LLM。图片、视频、TTS 和渲染仍需各自的计价单位与 Provider 合同。

## 3. 数据模型

### 3.1 ModelPricingProfile

`model_pricing_profiles` 以 `model_profile_id` 为主键，保存模型当前价格。删除 ModelProfile 时当前价格一起删除。

价格是未来调用的配置，不是历史账单。历史调用永远读取 RuntimeCostEntry 中的快照。

### 3.2 RuntimeCostEntry

每个已接收的 Provider usage 对应一条不可变费用记录：

- Plan、Task、Attempt；
- 稳定 `usage_key`；
- Provider / Adapter / Model 快照；
- Provider response ID；
- 完整价格快照与 SHA-256；
- token usage 与 cached token；
- 分项费用；
- `amount_microunits`；
- 是否完整计价；
- 创建时间。

唯一约束：

```text
UNIQUE(plan_id, usage_key)
```

Provider 和 Model 字段不使用外键。渠道后来删除或重建时，历史账目仍可解释。

## 4. Agent 价格冻结

第一次打开真实 LLM Provider 请求前，Agent 把以下内容写入 RuntimeTask checkpoint：

```text
provider_profile_id
provider_name
adapter
model_profile_id
model_id
capability_type
pricing
pricing_updated_at
snapshot source / version
```

checkpoint 提交后才创建外部 HTTP 请求。后续 Attempt 会继续使用该快照；模型当前价格改变不会影响已经开始的 Turn。

旧 checkpoint 如果已经产生 token、但没有价格快照，会被标记为 `legacy_unpriced`。系统不会用升级后的当前价格倒算旧调用。

## 5. Usage 与计算

OpenAI streaming Adapter 请求 `include_usage`，在流结束时发出 Provider response ID、实际 model ID 和 usage。JSON protocol Adapter从非流式响应读取同样字段。

费用使用 Decimal half-up 规则：

```text
普通输入费用 = (prompt - cached) × input rate / 1,000,000
缓存输入费用 = cached × cached rate / 1,000,000
输出费用     = completion × output rate / 1,000,000
总费用       = 以上三项 + request fee
```

如果没有单独缓存价格，则缓存 token 使用普通输入价格。

若配置了 token 价格但 Provider 没有返回输入/输出 usage，调用会保留已知 request fee，同时标记为 `priced=false`。工作台显示“未定价/不完整”，成本合计不能被误解为完整账单。

## 6. Exactly-once 账本语义

收到 usage 后，以下内容在同一个数据库事务中提交：

1. RuntimeCostEntry；
2. Task usage 水位；
3. Plan Budget Ledger；
4. Plan usage JSON；
5. `plan.cost.recorded` 事件；
6. 可能的 `agent.budget.exceeded` 事件。

相同 `usage_key` 重放返回原 CostEntry，不再次增加 token 或 cost。

Task heartbeat 仍上报绝对 usage。由于 CostEntry 已经推进 Task 水位，后续 checkpoint heartbeat 只看到零增量，不会把同一 Provider usage 算两次。

## 7. 成本预算

Agent Plan 默认成本上限：

```text
10 USD
```

Plan 也可显式使用：

```json
{"max_cost_microunits": 2000000}
```

或创建边界的 USD 别名：

```json
{"max_cost_usd": 2}
```

### 调用前

当当前成本已经达到上限，Runtime 在 Adapter 发出下一个 Provider HTTP 请求前失败。该调用不会发生，也不会产生 CostEntry。

### 调用后

Provider 响应可能让成本从上限以下跨到上限以上。系统先提交真实 CostEntry 和 Ledger，再发出预算超限控制信号。Agent Turn 失败关闭，已经发生的费用事实不会因异常回滚。

## 8. API 与工作台

```http
GET /api/runtime-plans/{plan_id}/budget
GET /api/runtime-plans/{plan_id}/costs
GET /api/turns/{turn_id}/budget
GET /api/turns/{turn_id}/costs
```

工作台模型设置支持输入、输出、缓存输入和单次请求价格。模型能力表显示价格覆盖情况。

Agent Turn 底部显示：

- 当前 USD 成本；
- token 数；
- Provider 调用数；
- 成本上限；
- 未完整计价调用告警；
- 最近费用明细；
- 预算超限提示。

运行中的 Plan 自动刷新；进入终态后停止周期轮询。

## 9. 已验证不变量

自动测试覆盖：

- USD → 微单位规范化；
- cached token 分项计算；
- 无 Provider usage 时不伪装完整计价；
- Provider API 保存并返回规范价格；
- 价格快照不受后续改价影响；
- CostEntry exactly-once；
- token / cost Ledger 不重复累计；
- 未定价调用仍进入审计；
- 调用后跨预算时费用先提交；
- 已到成本上限时下一次调用前拒绝；
- fresh migration 表、唯一约束和 Alembic head；
- 前端价格表单的微单位往返。

## 10. 当前边界

1. 外部 Provider 请求本身尚无通用 exactly-once：若进程在 Provider 已计费、但 usage 尚未提交前崩溃，恢复可能重新请求；需要 Provider idempotency key、异步 request ledger 或账单对账。
2. 只有返回 usage 的 LLM Adapter 可以完整按 token 计价。
3. 未定价调用只告警，不会按未知金额阻断；严格成本合规需要项目策略要求所有模型先配置价格。
4. 图片、视频、TTS、渲染和存储成本尚未接入。
5. Provider 官方价格自动同步、价格生效时间和多币种尚未实现。
6. CostEntry 是内部预算审计，不替代 Provider 最终账单。

## 11. 回滚

ModelPricingProfile 是当前配置；RuntimeCostEntry、Budget Ledger 和事件是历史事实。应用回滚不应删除或重算已记录费用。

数据库 downgrade 会删除成本明细与当前模型价格，但生产回滚应优先保留 `0014` 表，等待兼容版本继续审计。
