# Provider Request 自动对账

> 状态：Agent LLM 的响应 ID 早期持久化与后台终态对账已实现。  
> 日期：2026-08-13。  
> 复用 `runtime_provider_requests`，无新增迁移。

## 契约

OpenAI streaming 与 JSON protocol Adapter 一看到上游 `id`，就在短事务中验证当前 RuntimeTask claim，并写入 `provider_request_id`。它不等待完整响应、usage 或 CostEntry，因此流中断后仍保留外部身份。

渠道可配置：

```json
{
  "request_status_path": "/v1/requests/{request_id}",
  "request_status_field": "status",
  "request_status_provider_id_field": "id",
  "request_status_completed_values": ["completed", "succeeded"],
  "request_status_failed_values": ["failed", "error"],
  "request_status_pending_values": ["queued", "running"],
  "request_status_timeout_seconds": 20
}
```

查询路径必须包含 `{request_id}`，且不能改变 Provider 的 scheme 或 host。request ID 会进行 path 编码；查询复用渠道认证与 headers，但不会发送 Prompt 或工具参数。

## Recovery

Agent Executor 使用 `ReconciledTaskRuntime`。启动和周期 reaper 在完成 lease、timeout、审批与 stale dispatch 恢复后，读取最多 50 个：

```text
status = outcome_unknown
provider_request_id 非空
距上次观察至少 15 秒
```

网络查询在数据库事务外执行；单个 Provider 失败不会阻塞其他请求。每次观察更新 `updated_at`，限制轮询频率。

状态处理：

```text
pending   → 保持 outcome_unknown
completed → resolved / completed_external
failed    → resolved / failed_external
```

自动对账只补全审计，不会恢复失败 Turn、重发原请求、创建业务实体、伪造 usage 或补记 CostEntry。需要继续业务时必须显式新建 Turn、Retry 或 Replan。

未配置 `request_status_path` 时继续 fail-closed，并使用现有 `/api/runtime-provider-requests/{id}/resolve` 人工对账。`idempotency_header` 与状态查询是两项独立能力。

## 验证与边界

测试覆盖同源限制、嵌套状态字段、认证 header 以及 completed / pending 映射；分支 CI 继续执行后端全量测试、前端测试、lint、设计检查和生产构建。

当前生产接入仅覆盖 Agent LLM。图片、视频、TTS 与渲染仍由旧 JobEngine 执行，尚未具备统一 RuntimeTask claim；Provider 查询结果也尚无通用 usage/cost 合同，因此外部 completed 只解析状态，不自动补记费用。
