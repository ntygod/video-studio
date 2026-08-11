# Video Studio · 通用创作工作台

一个开放式的 AI 创作系统：用户可以创作任意数量、任意类型、任意层级的内容，系统不预设"剧集""短视频""科普"等产品边界。

## 核心概念

- **项目（CreativeProject）**：一次完整创作。项目类型、工作流、格式均为开放文本标识，可以由用户自由定义。
- **创作单元（CreativeUnit）**：任意层级的内容节点，例如章节、场景、镜头、广告活动、产品变体、研究文档。单元没有数量上限，unit_type、stage、custom_fields 全部开放。
- **Artifact**：可版本化的创作产物（Brief、Bible、剧本、分镜、时间线等）。AI 不能直接修改，只能提交 ChangeProposal，用户接受后生成新的追加版本。
- **资产（Asset）**：项目内的图片、视频、声音、字幕、渲染结果等媒体文件，关联到任意创作单元或镜头。
- **任务（Job）**：持久化的生成/渲染任务，重启后仍保留状态、事件与失败信息。
- **模型渠道（Provider Profile）**：LLM、图片、视频、配音等能力均可配置外部 base_url / api_key / 模型。`openai` 适配器走 OpenAI 兼容协议与原生 tool calling，其余适配器回落到 JSON 协议模拟。

## 快速开始

~~~powershell
# 后端（127.0.0.1:8765）
.\run.ps1

# 前端（http://127.0.0.1:3000）
cd web
pnpm install
pnpm dev
~~~

前端通过 `next.config.ts` 的 rewrites 把 `/api/*` 与 `/media/*` 代理到后端，默认不需要配置 `NEXT_PUBLIC_SERVER_URL`。

## 数据目录

- data/studio.db：项目、单元、对话、Artifact 版本、提案、模型渠道、任务（SQLite，WAL）
- data/media/：项目媒体资产，经后端 `/media/{project_id}/{path}` 提供
- data/work/：渲染中间文件

## API 摘要

- /api/projects：项目 CRUD
- /api/projects/{id}/units：任意创作单元树
- /api/projects/{id}/artifacts、/api/artifacts/{id}/versions：版本化 Artifact
- /api/proposals：AI 变更提案的接受/拒绝
- /api/conversations：多轮对话创作
- /api/provider-profiles、/api/model-capabilities：统一模型配置
- /api/jobs：持久化任务
- /media/{project_id}/{path}：媒体文件

## 前端结构

~~~
web/src/
  app/
    (user)/          项目库、任务中心、模型设置（带全局侧栏）
    (workspace)/     项目工作台（三栏，无全局侧栏）
      projects/[id]/{story,media,produce,brief}
  features/
    workspace/       三栏 shell、顶栏、路由与共享数据 hook、UI store
    structure/       创作单元树、完成度、新建单元
    agent/           AI 助手面板、消息流、输入框
    canvas/          四个画布视图与稿件/提案组件
    jobs/            底部任务坞
    settings/        模型渠道表单
  services/
    api/             按域拆分的后端调用（http / types / projects / artifacts / ...）
    queries/         React Query 的 key 工厂与 hooks，组件只从这里取数据
  shared/            通用 UI 原子、格式化、媒体查询、主题
~~~

约定：

- **服务端数据一律走 `services/queries`**，不要在组件里写 `useEffect` + `fetch`，也不要把服务端数据放进 zustand。
- **视图与选中单元存在 URL 上**（路由段 + `?unit=`），保证刷新、后退、分享链接都能恢复。
- **antd 只做控件**，容器与布局用 Tailwind + `--studio-*` 令牌自绘。详见 `docs/design-tokens.md`。

## 文档

- `docs/ui-redesign.md`：UI 重构方案与分阶段计划
- `docs/design-tokens.md`：设计令牌与使用约定
