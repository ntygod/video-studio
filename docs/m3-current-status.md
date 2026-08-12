# M3 当前状态 · 2026-08-12

`docs/m3-freshness-and-regeneration.md`、`docs/regeneration-cascade-preview.md` 与 `docs/regeneration-plan-execution.md` 共同描述当前能力。

本阶段已经具备：精确 ArtifactVersion / Asset 输入、stale / blocked 传播、单点 LLM 与 Timeline 修复、只读拓扑预览、持久化 RegenerationPlan / Step、按依赖释放 Job、Job 终态与重启恢复、工作台计划创建/启动/取消/素材替换/历史重开。

当前边界：尚无数据库级 Step claim；多应用进程应只运行一个计划协调器；尚无失败 Step Retry/Replan、needs_review 继续、可配置部分成功策略、强制外部 Provider 取消、生成 Asset Freshness 节点与 500 节点压力基线。

本文件用于在旧文档全部完成同步前提供不歧义的当前状态入口。
