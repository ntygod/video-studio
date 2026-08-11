# 实施记录（docs/roadmap.md 施工日志）

> 本文件记录 roadmap 各阶段收尾时的关键证据，供验收审计使用。

## Phase 0 收尾

- T0.1：`pnpm build` 通过（Next 16 + Turbopack，含 TypeScript 校验）。
  已删除 P0 遗留：`emotion-curve.tsx`、`canvas-theme.test.ts`、`components.json`、`tsconfig.tsbuildinfo`、
  以及 workflow 相关后端/前端代码（`workflow.py`、`workflows.py`、`WorkflowRepository`、`listWorkflows` 等）。
- 产物体积记录（2026-08-09）：
  - `web/.next` ≈ 243.68 MB（standalone 输出，含静态资源与依赖）
  - `web/src` ≈ 0.46 MB
  - 仓库无 P0 之前的构建产物基线（初始仓库没有历史提交/旧体积记录），因此 ≥30% 的降幅无法做数值对比；
    但计划列出的删除清单已全部落地，`pnpm build` 自带类型校验通过。
- T0.3：`data/studio.db` 已删库重建，实际库内含 `units_fts` / `artifacts_fts` / `agent_turns` / `agent_steps`，
  无 `workflows` 表。
- T0.4：全仓 `rg -ri workflow` 仅剩 `CreativeProject.workflow_id` 开放文本字段及其读写映射。

## 测试证据（最终回归，2026-08-09）

- 后端：`.venv/Scripts/python -m pytest tests/ -q` → 38 passed
- 前端：`pnpm test` → 10 passed
- 类型：`npx tsc --noEmit` → 无错误
- 构建：`pnpm build` → 通过（`next.config.ts` 已删除 `typescript.ignoreBuildErrors`）

## 各阶段覆盖

- Phase 1：LLM 适配器（openai/anthropic/json）、12 步 Agent 循环 + 11 个工具、SSE 回合流、
  回合持久化与撤销、提案预览/逐条采纳、deep_merge、artifacts 列表 N+1 修复。
- Phase 2：有界 4-worker Job 引擎（原子认领 + lease 回收 + 2^n 退避 + 协作式取消）、任务 SSE、
  进度统一 0–1、媒体管线（相对 uri / ffprobe / 缩略图）、批量生成、provider 连接测试、
  X4/X6/D6/兜底 500 修复；前端分镜墙/素材库/任务坞/能力优先设置页。
- Phase 3：游标分页、项目详情瘦身、FTS5（trigram）检索、单元连贯性摘要 + 对话滚动压缩 + pinned_refs、
  项目列表聚合字段；前端虚拟化结构树、筛选/搜索/拖拽/多选、圣经面板、项目库卡片。
- Phase 4：时间线编译三处修复（edit_plan 择优、asset_id 真 id、配音对齐）、ffmpeg 进度解析、
  版本 diff/回滚、版本状态机只进不退；前端时间线/版本/分体裁故事渲染 + 块级改写。
- Phase 5：⌘K 命令面板、全键盘（树导航/Space 多选/Esc 关浮层/焦点陷阱）、aria-live 播报、
  空/错/载状态统一、768–1280 平板两栏、关掉 ignoreBuildErrors、结构化日志 + request_id
  贯穿 job payload / agent step / SSE 事件。

## 说明

roadmap 中的产品级性能验收项（首 token < 2s、500 单元 60fps、1000 条搜索 < 100ms 等）
依赖真实 LLM/媒体渠道与基准环境，本仓库未配置外部密钥，未做线上基准；对应机制
（流式 SSE、虚拟化、FTS5、分页、压缩）均已实现并由测试覆盖。

## 运行时验收（2026-08-09，真实启动前后端）

启动方式：后端 `uvicorn app.main:app --port 8765`（PID 15104），前端 `.next/standalone/server.js`（端口 3000，构建后复制 static/public）。
`GET /api/health` → ok / db_ok / media_root_ok 全 true。

验收覆盖（应用内浏览器实际操作）：
- 首页项目库 → UI 创建项目 → 跳转 `/projects/{id}/story`。
- 三栏工作台（结构 + 主区 + 助手）、⌘K 命令面板（打开/过滤/回车执行/Esc 关闭）、
  新建创作单元、结构树 Space 多选 →「交给 Agent」→ 助手上下文 chip 即时出现、
  ArrowUp 回到整个项目。
- 7 个视图（故事/分镜/素材/成片/设定/时间线/版本）逐一导航，无错误面板。
- 平板 900×800：结构栏内联、助手走抽屉，抽屉可开可关、Esc 可关闭。
- 设置页：能力优先布局、「尚未配置的能力」、模型能力总览正常。
- 生产构建新开标签页冒烟：故事页 + 设置页 0 控制台错误。

运行时发现并修复的问题：
1. `/projects/[id]` 服务端重定向页从 "use client" store 导入 `DEFAULT_CANVAS_VIEW`，
   Next 把它序列化成客户端函数代理 → 重定向 URL 变成函数代码并 404。
   修复：视图常量/工具迁到 `web/src/features/workspace/lib/canvas-views.ts`（无 "use client"）。
2. 结构面板「交给 Agent」后，已挂载的 Agent 面板不会立即取走上下文（只在挂载/切单元时 drain）。
   修复：AgentPanel 订阅 `pendingContextRefs.length`。
3. `globals.css` 一处残缺注释（`bg-*/text-*`）导致 dev 服务器 500、生产构建 CSS 警告。修复注释。
4. 三个弹窗（ProviderFormModal / UnitCreateModal / BatchGenerateModal）的 `forceRender`
   导致设置页 SSR/客户端结构不一致（Hydration #418 + script 标签警告）。移除 forceRender。
5. 平板图标态下顶栏 tab 链接补 aria-label；antd v6 弃用项 `maskClosable` → `mask={{ closable: true }}`、Drawer `width` → `size`。

修复后回归：`pnpm test` 10 passed、`npx tsc --noEmit` 无错误、`pnpm build` 通过（CSS 警告消失）。
验收项目已删除，项目库恢复 0 项目。

## UI 精细化落地（2026-08-10，docs/ui-craft.md C1–C6）

决策（§7 已定稿）：强调色降饱和青柠 `#b8e05f`、界面字体 Inter（自托管）、C3 一次全改。

- C1 新令牌集：`--s-canvas/base/panel/raised/overlay`、hairline/lift、`--r-*`、`--sp-*`、
  `--ease-out/--ease-in-out`、排版七档（display 28 → mono-sm 11.5）；接入
  `@fontsource-variable/inter`，删除 Bricolage；antd 镜像同步（app-theme.ts），
  Button/Input/Select/Modal/Tooltip 等按 §5 收编。
- C2 组件层：`web/src/shared/ui` 新增 surface/card/stack/text/divider/field/button/
  icon-button/chip/progress/skeleton/media-frame/checkbox + antd 包装（inputs/overlays/misc/
  providers），预览页 `/ui`；ESLint 规则禁止手抄容器、10px、features 直引 antd；
  `scripts/check-tokens.mjs`（幽灵令牌）与 `scripts/check-ui.mjs`（量化验收）。
- C3 全量重写：48 个文件完成 `--studio-*` → `--s-*` 迁移，17 处手抄容器、20 处 10px、
  30 处 features 直接引 antd 全部清零；两个幽灵令牌（`--studio-shadow-md` /
  `--studio-danger-soft`）随分镜卡与运行轨迹重做消失。
- C4 关键界面：分镜卡（媒体出血/整卡点击/自绘勾选/shimmer+进度环/hover 操作条）、
  运行轨迹（四列对齐/失败左竖条/内联进度）、项目库封面优先、空状态去虚线框。
- C5 动效：面板开合 `panel-transition`、流式光标、重排 FLIP 位移、状态点 pop、
  进度条改 `--s-ink` 单色。
- C6 验收：`pnpm test` 10 passed；`pnpm lint` 0 error；`pnpm check` 全绿
  （幽灵令牌 0 / 10px 0 / 手抄容器 0 / features 引 antd 0 / 对比度全 ≥ 4.5:1，
  `scripts/check-contrast.mjs`）；`pnpm build` 通过（11 条路由 + /ui 预览页）。

### 最终视觉验收补记（2026-08-10，隔离构建 + 应用内浏览器截图）

隔离验证：`NEXT_DIST_DIR=.next-ui-craft` 独立构建，standalone 跑在 3001，未动 3000 的旧服务。
暗/亮两套主题在 /ui 与首页截图核对，发现并修复三处"运行时才暴露"的问题：

1. antd `App` 根节点默认注入系统字体栈，把 Inter 盖掉；且 `fontSize: 13` 把
   `fontSizeSM / fontSizeIcon` 推导成 10px。修复：app-theme.ts 的 token 增加
   Inter 字体链并显式 `fontSizeSM: 12`、`fontSizeIcon: 12`。
2. tailwind-merge 把未知的 `text-title / text-caption / text-mono-sm` 等自定义字号类
   当作颜色类，与 `text-[var(--s-*)]` 冲突后直接丢弃（DOM 里 class 消失、字号全部回退 13px）。
   修复：utils.ts 用 `extendTailwindMerge` 把七档字号声明进 v3 的 `theme.text`。
3. `antd/dist/reset.css` 的无层规则（h1–h6 500 字重、p 1em 下边距）压过 Tailwind v4
   的 utilities 层，标题无论 `font-semibold` 都算成 500。修复：新建
   `web/src/app/antd-reset.css`，用 `@import ... layer(antd-reset)` 收进
   Tailwind 之前的层（layout.tsx 改为引它）。

修复后运行时复核：暗/亮两套 /ui 与首页字号全部落在 11–28px（无 10px），
拉丁字符与 antd 控件实际渲染 Inter，display 28/Syne 600、title 19、heading 15、
body 13.5、label 12、caption 11、mono-sm 11.5；控制台 0 error。
回归：`pnpm lint` 0 error、`pnpm test` 10 passed、`pnpm check` 全绿。
验证构建与 3001 服务已清理，next.config.ts / tsconfig.json 已还原。
随后用还原后的配置正式 `pnpm build` 通过，3000 端口的旧 standalone 已替换为新构建
（static/public 已复制，/ 与 /ui 均 200，运行时抽查 Inter/字号/字重全部符合）。
