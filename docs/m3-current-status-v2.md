# M3 持久化修复权威状态 · 2026-08-12

当前实现已包含：精确 ArtifactVersion / Asset 输入，stale / blocked 传播，单点 LLM 与 Timeline 修复，只读拓扑预览，持久化 RegenerationPlan / Step，按依赖释放 Job，Job 终态与重启恢复，以及工作台计划创建、启动、取消、素材替换与历史重开。

详细执行不变量见 `docs/regeneration-plan-execution.md`。当前主要边界是多进程 Step claim、失败 Step Retry/Replan、needs_review 继续、可配置部分成功、外部 Provider 强制取消、生成 Asset Freshness 节点与大图压力基线。
