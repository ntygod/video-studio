# Runtime Provider 成本计量与严格策略

> 状态：Agent LLM 价格快照、不可变费用明细、硬成本预算与项目级严格计价均已实现。  
> 日期：2026-08-13。  
> Alembic revision：`20260812_0014`；严格策略复用 Project settings，无新增表。

## 1. 目标

Runtime 成本链路为：

```text
ModelProfile 定价
  → Project Provider 成本策略
  → RuntimePlan 冻结策略与价格
  → Provider 返回 usage
  → RuntimeCostEntry
  → Plan / Task Budget Ledger
  → 成本预算判断与工作台展示
```

系统保证：

1. 改价不重写历史调用；
2. 同一 usage 事件重放不重复计费；
3. Provider 已经发生的费用不能因预算异常而回滚；
4. 到达预算上限后，下一次 Provider 调用在 HTTP 请求前被拒绝；
5. 缺少价格或 usage 时不伪造零成本；
6. 项目可以选择允许未完整计价，或要求新 Agent 回合严格计价。

## 2. 价格表示

当前只支持 USD，持久化使用整数微美元：

```text
1 USD = 1,000,000 microunits
```

LLM 模型可配置输入、输出、缓存输入和单次请求价格。API 与工作台接受 USD，并在写入边界规范化为整数。显式 0 是有效价格，可用于免费或自托管模型；只填写 currency 不算价格配置。

## 3. 数据模型

### 3.1 ModelPricingProfile

`model_pricing_profiles` 保存模型当前价格。它只影响未来第一次冻结价格的调用；历史账目使用 RuntimeCostEntry 快照。

### 3.2 RuntimeCostEntry

每个已接收的 Provider usage 对应一条不可变费用记录，包含 Plan、Task、Attempt、稳定 `usage_key`、Provider/Model、价格 SHA-256、usage、分项金额、`priced` 和创建时间。

唯一约束：

```text
UNIQUE(plan_id, usage_key)
```

Provider 和 Model 快照不使用外键，因此配置删除后历史费用仍可解释。

## 4. 价格与策略冻结

第一次真实 LLM 请求前，Agent 把 Provider、Model、价格、价格更新时间和 snapshot source 写入 RuntimeTask checkpoint。

新建 `agent.turn` RuntimePlan 时，还会从项目 settings 冻结：

```json
{
  "provider_cost_policy": {
    "unpriced_provider_mode": "allow"
  }
}
```

项目后来切换策略不会重新解释已经开始或等待恢复的 Plan。显式调用方策略可以覆盖项目默认，但同一 Plan 内不漂移。

旧 checkpoint 已产生 token 却没有价格快照时标记为 `legacy_unpriced`，不会用升级后的当前价格倒算。

## 5. Usage 与计算

OpenAI streaming Adapter 请求 `include_usage`；兼容网关拒绝该字段时，只在尚未生成内容的 400/422 响应上降级重试一次。JSON protocol Adapter读取非流式 usage。

费用公式：

```text
普通输入费用 = (prompt - cached) × input rate / 1,000,000
缓存输入费用 = cached × cached rate / 1,000,000
输出费用     = completion × output rate / 1,000,000
总费用       = 以上三项 + request fee
```

配置 token 价格但 Provider 不返回 usage 时，会保留已知 request fee，并记录 `priced=false`。

## 6. Exactly-once 账本

以下内容在一个事务中提交：

1. RuntimeCostEntry；
2. Task usage 水位；
3. Plan Budget Ledger；
4. Plan usage JSON；
5. `plan.cost.recorded`；
6. 可能的预算超限事件。

相同 `usage_key` 重放返回原条目，不再次增加 token 或 cost。后续绝对 usage heartbeat 只产生零增量。

## 7. 成本预算

Agent Plan 默认成本上限为 10 USD，也可使用 `max_cost_microunits` 或创建边界的 `max_cost_usd`。

当前成本达到上限时，下一个 Provider 请求在发出前失败。响应跨越上限时，系统先提交真实 CostEntry 和 Ledger，再失败关闭 Turn。

## 8. 项目级未定价策略

项目可选择：

### `allow`：尽力计价

默认值，保持向后兼容。缺少模型价格或 usage 的调用继续执行，但 CostEntry 标记 `priced=false`，工作台显示未完整计价。成本上限可能低估真实支出。

### `block`：严格计价

新 Agent Plan 必须满足：

- 模型有显式价格配置；
- token 计价模型的响应返回可计量 usage。

执行边界：

1. **请求前**：没有价格配置时，写入唯一的 `runtime.cost_policy.blocked` 事件，并在打开外部请求前失败；不产生 CostEntry。
2. **响应后**：Provider 已返回成功内容但缺少 usage 时，先提交 `priced=false` CostEntry，再写阻断事件并失败关闭。已经发生的外部调用与 request fee 不回滚。

严格策略复用 `RuntimeBudgetExceeded` 的持久化硬终止通道，因此不会被普通异常自动重试。事件按 Task、阶段、Provider、Model 与 CostEntry 语义去重。

## 9. API 与工作台

```http
GET   /api/projects/{project_id}/runtime-cost-policy
PATCH /api/projects/{project_id}/runtime-cost-policy
GET   /api/runtime-plans/{plan_id}/budget
GET   /api/runtime-plans/{plan_id}/costs
GET   /api/turns/{turn_id}/budget
GET   /api/turns/{turn_id}/costs
```

策略更新使用项目 revision 乐观锁，并通过 PatchProjectCommand 进入 OperationLog。工作台顶栏“成本策略”抽屉可以切换尽力/严格模式，并提示免费模型也应显式配置 0 价格。

Agent Turn 显示 USD、token、调用数、上限、未定价告警和费用明细。

## 10. 已验证不变量

测试覆盖：

- USD 与微单位规范化；
- cached token 分项计算；
- Provider API 与价格快照；
- CostEntry、token 与 cost exactly-once；
- 请求前成本门限和请求后真实费用保留；
- 未定价允许模式的审计；
- 项目策略更新的 revision 与 Operation 审计；
- Agent Plan 策略冻结；
- 严格模式在无价格时不调用 Provider；
- 严格模式在缺少 usage 时先保存 unpriced CostEntry 再失败；
- 阻断事件语义去重；
- 前端策略规范化、类型、lint、设计检查与生产构建。

## 11. 当前边界

1. 外部 Provider 请求尚无通用 exactly-once；Provider 已计费但 usage 提交前崩溃仍可能重请求。
2. 严格模式只能验证本系统配置和返回 usage，不替代 Provider 最终账单。
3. 图片、视频、TTS、渲染与存储成本尚未接入。
4. 官方价格同步、生效时间、多币种和账单对账尚未实现。
5. 项目策略目前只有 allow/block，尚无按 Provider、模型、角色或预算区间的细粒度规则。

## 12. 回滚

项目成本策略和 ModelPricingProfile 是当前配置；RuntimeCostEntry、Ledger、Event、Operation 与业务版本是历史事实。应用回滚不应删除或重算记录。旧版本会忽略新增 settings 字段，但生产回滚应优先保留 `0014` 表。
