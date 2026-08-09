# Video Studio 新 UI 方案 v1

> 目标：把当前"带聊天侧栏的表单式 CRUD 应用"改造成 **Agent 驱动的创作工作台**，支持自由创作图片 / 视频，并能承载长篇、持续、多单元的创作。
>
> 本文只覆盖 **UI / 前端**。后端只列出"UI 必须依赖的契约"（第 7 节），完整后端方案单独出。

---

## 0. 结论先行

当前 UI 的根本问题不是"不好看"，而是 **产品模型错位**：

| 你想要的 | 现在实现的 |
|---|---|
| Agent 驱动 | Agent 是右侧 360px 的附属聊天框，产出只能变成中间一个黄色提示条 |
| 自由创作图片/视频 | 没有任何图片/视频生成入口（`startGeneration` 只被用来生成一份剪辑 JSON） |
| 长篇持续创作 | 一次 `GET /api/projects/{id}` 拉回全部 units + 全部 artifact payload；单元列表是扁平 `map()`；每次操作全量 `load()` 刷新 |
| 创作工作台 | 4 个 antd Tabs（创作 / 创作设定 / 素材 / 生成视频） |

新 UI 的核心主张是三句话：

1. **对话是驱动器，不是侧栏。** Agent 要有可见的运行轨迹、可见的上下文、可逐条采纳的提案。
2. **作品要看得见。** 稿件按体裁渲染（剧本就长得像剧本），分镜是卡片墙，时间线是轨道，素材有血缘。而不是统一的 key-value 转储。
3. **结构要扛得住长度。** 虚拟化树 + 完成度环 + 按需分页 + `@` 引用定位上下文。

---

## 1. 现状诊断（带证据）

### 1.1 前端结构

| 问题 | 证据 |
|---|---|
| 工作台是一个 765 行单组件，19 个 `useState` | `web/src/app/(user)/projects/[id]/page.tsx` |
| 全量刷新：一次 `load()` 打 4 个接口，任何操作后都调用 | 同上 `:93-124`；`saveBrief` / `addUnit` / `saveArtifact` / `decideProposal` / `doUpload` 全部 `await load()` |
| 发一条消息触发 6 次请求 | `send()` `:311` → `sendMessage` + `getConversation` + `load()`×4 |
| `load` 依赖 `conversation`，只能靠 eslint-disable 压住 | `:126-130` |
| React Query 装了 Provider 但零使用 | `app-providers.tsx:64` 有 `QueryClientProvider`；全仓库 `useQuery`/`useMutation` **0 处命中** |
| 10 个重依赖完全未被 import | `@xyflow/react`、`echarts`、`@uiw/react-codemirror`、`@assistant-ui/react`、`localforage`、`fflate`、`file-saver`、`copy-to-clipboard`、`motion`、`axios`、`nanoid` — 全部 0 处命中 |
| 结构化稿件编辑 = 裸 JSON textarea | `:761`（CodeMirror + json 语言包已装但没用） |
| 视图状态不进 URL | Tab / 选中单元 / 选中稿件全在内存，刷新即丢，不可分享 |

### 1.2 缺失的界面

后端已经具备、前端完全没有 UI 的能力：

- **`TimelineIR`**（`app/domain/timeline.py`）：tracks / clips / keyframes / volume / speed，有完整渲染链路 → **零 UI**
- **Artifact 版本链**：`version` / `status(draft|proposed|approved|locked)` / `parent_version_id` / `source` → UI 只显示"第 N 版"，看不了历史、比不了差异、回不去
- **图片 / 视频生成**：`job_engine._run_media` 支持 image/video → UI 无入口
- **配音**：`voice_service` / `edge-tts` → UI 无入口
- **Workflow 图**：`app/domain/workflow.py` + nodes/edges → UI 无入口（xyflow 装了没用）
- **Proposal 的 `operations` 数组**：JSON-Patch 式逐条操作 → UI 只有"全采用 / 全拒绝"

### 1.3 长篇的硬伤

```python
# app/api/routes/projects.py:56
@router.get("/{project_id}")
def get_project(...):
    return {
        **project.model_dump(mode="json"),
        "units": [...uow.units.list(project_id)],        # 全部单元，无分页
        "artifacts": uow.artifacts.list(project_id),      # 全部稿件，含完整 payload
        "pending_proposals": [...],
    }
```

```python
# app/application/conversations.py:33
context = {"project": project_json, "selected_unit_id": unit_id, "artifacts": artifact_context}
messages = [..., {"role": "system", "content": "当前项目上下文：" + json.dumps(context)}]
```

每轮对话把 **整个项目 + 所有 artifact 的完整 payload** 塞进 system prompt。20 章的项目就会爆上下文。这既是后端问题，也决定了 UI 必须提供 **显式的上下文选择**（第 4.2 节的上下文条）。

### 1.4 设计系统

- **三套 token 并存**：shadcn 的 oklch 变量（紫色系）+ `--studio-*` 十六进制（橄榄绿/青柠）+ antd ConfigProvider。视觉不自洽。
- `globals.css` 1660 行，同一个类被定义两次靠后者覆盖前者：`.studio-sidebar-rail` 在 `:585` 定义、`:1116` 又整体重写。
- token 冗余：亮色下 `--studio-glass` / `--studio-panel` / `--studio-panel-solid` / `--studio-surface` / `--studio-rail` **全部等于 `#ffffff`**。
- 字号随手写：`text-[10px]` / `text-[11px]` / `text-xs` / `text-sm` 混用，无梯度。

### 1.5 反馈与状态

- 无流式。`sendMessage` 阻塞等待；后端 `chat_json` 最多重试 3 次、每次 `timeout=600` → **最坏 30 分钟白屏无反馈**。
- 无 SSE。任务列表 4s 轮询、详情 2.5s 轮询（`jobs/page.tsx:63,88`）。
- 错误处理只有 `message.error` toast，没有分区错误边界、没有重试、没有骨架屏。

---

## 2. 新 UI 的产品模型

### 2.1 三区 + 一坞

```
对话（驱动）  ↔   画布（作品）  ↔   结构（长度）
                    ↓
                 任务坞（生产）
```

- **结构区**：我在长篇的哪个位置，还有哪些没做完
- **画布区**：我做出来的东西长什么样（可切 5 种视图）
- **对话区**：我让 Agent 做什么，它正在做什么，它想改什么
- **任务坞**：后台在跑什么（生成/渲染），常驻但不抢注意力

### 2.2 舞台自适应（Stage-adaptive Layout）

同一个工作台，随项目成熟度改变重心。这直接对应"从一句话开始 → 长篇持续创作"：

| 阶段 | 判定 | 布局 |
|---|---|---|
| **起步** | 无 artifact | Agent 居中（720px 单栏对话），左右收起。像 ChatGPT。 |
| **成形** | 有 artifact，无媒体 | 三栏，画布默认「故事」视图 |
| **生产** | 有 asset / job | 三栏 + 任务坞展开，画布默认「分镜」视图 |
| **收尾** | 有 edit_plan / render | 画布默认「时间线」视图 |

自动切换只发生一次并且可撤销（顶部出现 "已切换到分镜视图 · 撤销"），之后尊重用户手动选择（存 localStorage）。

---

## 3. 信息架构与路由

```
/                                   项目库（prompt-first）
/projects/[id]                      → 重定向到上次视图，默认 /story
/projects/[id]/story                画布 · 故事
/projects/[id]/board                画布 · 分镜
/projects/[id]/timeline             画布 · 时间线
/projects/[id]/media                画布 · 素材
/projects/[id]/versions             画布 · 版本
/jobs                               全局任务（跨项目）
/settings/models                    模型能力
/settings/appearance                外观
```

关键变化：

- **视图进 URL** → 可分享、可后退、可刷新恢复
- 选中单元进 query：`?unit=<id>` → 「把这个镜头发给同事看」变成可能
- 资产预览 / 版本对比用 **intercepting route**（`@modal`）：`/projects/[id]/media/[assetId]` 直接可访问，也可作为浮层打开
- **移除工作台内的 88px 全局 rail**。项目内左侧 100% 归结构导航；全局导航收进顶栏的项目切换器 + `⌘K` 命令面板

---

## 4. 界面设计

### 4.1 工作台 Shell

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◧ 迷失月球 ▾   第二卷 › 第7章 › 镜头12        ⌘K   ◐  ⚙  ● 3 任务      │ 48
├─────────────┬──────────────────────────────────────┬─────────────────────┤
│ 结构         │ [故事][分镜][时间线][素材][版本]  ⟳  │ Agent          ⤢ ✕ │
│             ├──────────────────────────────────────┤                     │
│ ◉ 项目总览   │                                      │  运行轨迹 ▾         │
│ ○ 第一卷 3/8 │                                      │  ─────────────      │
│  ├ 第1章 ✓   │                                      │  消息流             │
│  ├ 第2章 ◐   │            Canvas                    │   · 用户            │
│  └ …         │                                      │   · Agent（流式）   │
│ ● 第二卷 1/6 │                                      │   · 提案卡片        │
│  ├ 第7章 ◐   │                                      │                     │
│  └ …         │                                      │  ───────────────    │
│             │                                      │  上下文条           │
│ ── 连贯性 ── │                                      │  [第7章×][圣经×]    │
│ 角色 · 世界  │                                      │  ┌───────────────┐  │
│ 风格 · 已锁3 │                                      │  │ 输入…    [模式]│  │
│             │                                      │  └───────────────┘  │
├─────────────┴──────────────────────────────────────┴─────────────────────┤
│ ▴ 任务坞  分镜图 2/8 ▓▓▓░░░  ·  配音 排队中  ·  成片 —          [展开]   │ 32
└──────────────────────────────────────────────────────────────────────────┘
  260px         flexible                                420px
  可折叠→48px                                          可折叠 / 可全屏 ⤢
```

- 三栏用 `react-resizable-panels`（或自写 8 行的拖拽），宽度存 localStorage
- `⌘\` 折叠结构区，`⌘J` 折叠 Agent 区，`⌘⏎` 发送，`⌘K` 命令面板
- Agent 区 `⤢` 全屏 = 回到"起步"的居中对话形态，用于深度讨论

### 4.2 Agent 面板 —— 本次改造的核心

这是"Agent 驱动"的落地点。四个新东西：

#### (a) 运行轨迹（Run Trace）

Agent 不能只吐一段文字。每一步作为可折叠行显示：

```
┌─ 正在处理：为第7章生成分镜 ─────────────── 已用 24s  ⏹ 停止 ─┐
│ ✓ 读取  第7章 · 剧本 v3                              0.2s   │
│ ✓ 检索  角色圣经 · 林夏 / 陈默                        0.1s   │
│ ✓ 生成  分镜计划（12 个镜头）                        18.4s   │
│ ◐ 生成  概念图 3/12                                        │
│ ○ 提交  变更提案                                            │
└─────────────────────────────────────────────────────────────┘
```

状态点：`○` 待执行 `◐` 进行中 `✓` 完成 `✕` 失败（可展开看错误 + 重试单步）。

> 后端依赖：SSE 推送 step 事件（第 7 节 BE-1）。**在后端就绪前，可先用 job 事件流拼出轨迹**——`jobs.add_event(stage=...)` 已经在写 stage 了。

#### (b) 上下文条（Context Bar）

紧贴输入框上方，**显式声明这轮对话带了什么**：

```
上下文  [📄 第7章 剧本 ×] [👤 林夏 ×] [🖼 参考图 ×2 ×] [+ 添加]     ~4.2k tokens
```

- 默认按当前选中单元自动填充，用户可增删
- 支持输入框内 `@` 唤起选择器：`@第7章`、`@林夏`、`@ref-003`
- 右侧显示预估 token —— 长篇用户需要这个来控成本
- **这一条同时解决了 1.3 的后端硬伤**：前端声明上下文，后端按 `context_refs` 组装，不再全量转储

#### (c) 内联提案卡片（Inline Proposal）

提案回到消息流里，不再是中间栏一个黄块。并且 **逐条采纳**：

```
┌ 建议修改 · 第7章 · 分镜计划 ─────────────────────────┐
│ 把镜头 8-10 合并为一个长镜头                          │
│ 理由：连续三个特写切换过快，破坏了追逐段落的压迫感      │
│                                                       │
│ ☑ 删除 shots[8]                        ⌄ 查看        │
│ ☑ 修改 shots[7].duration  3.2s → 8.5s                │
│ ☐ 修改 shots[7].camera    "特写" → "手持跟拍"         │
│                                                       │
│ [采用勾选的 2 项]  [全部采用]  [拒绝]  [完整对比 ⧉]    │
└───────────────────────────────────────────────────────┘
```

- 每条 operation 一行，字段级 before → after
- `完整对比` 打开版本 diff 浮层
- 采纳后卡片原地变为 `✓ 已采用 2 项 · v3 → v4  [查看]`

> 后端依赖：`POST /api/proposals/{id}/accept {op_indices:[...]}`（BE-6）。未就绪前先做全量采纳 + 字段级预览。

#### (d) 创作模式（Composer Mode）

输入框右下角切换，决定 Agent 走哪条能力链：

`讨论`（不产生提案）· `写作`（→ artifact）· `生成图`（→ image job）· `生成视频`（→ video job）· `配音`（→ tts job）· `剪辑`（→ edit_plan）

选「生成图」时输入框下方展开一条紧凑参数行：尺寸 / 数量 / 参考图 / 风格锁定（勾选后自动注入圣经的 `style.visual_direction` + `negative_prompts`）。

**这是"自由创作图片/视频"的主入口，当前完全没有。**

### 4.3 画布 · 故事（Story）

替换现在的 `ArtifactContentView` 通用转储。**按 artifact kind 分派渲染器**：

| kind | 渲染 |
|---|---|
| `outline` | 可折叠嵌套大纲，拖拽重排 |
| `script` / `screenplay` | 剧本排版：场景标题居左大写、角色名居中、对白缩进、动作正文 |
| `shot_plan` | 镜头表格 / 卡片（与分镜视图共用组件） |
| `analysis` / `generated` | 文档流 |
| 未知 kind | 回落到现在的 `ArtifactContentView`（保底，不阻塞） |

关键交互：**块级 AI 改写**。悬停任意段落 / 场景 / 镜头，右侧浮出 `✨`：

```
  林夏推开门，走廊尽头的灯忽明忽暗。          [✨ 改写] [⋯]
  她数了三下，才敢往前迈。
```

点击 → 该块内容作为上下文塞进 Agent 输入框，预填 "改写这段：…"。这让 Agent 能在段落粒度工作，而不是每次重写整份稿件。

顶部工具条：`版本 v4 ▾`（切历史版本预览）· `状态: 草稿/已采用/已定稿` · `🔒 定稿` · `⧉ 对比` · `{} 源码`（这里才用 CodeMirror，替掉裸 textarea）。

### 4.4 画布 · 分镜（Board）—— 图片/视频创作主场

```
第7章 · 12 个镜头        [全选] [批量生成 ▾] [排序: 顺序 ▾]   ⊞ ☰
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ ▓▓▓▓▓▓▓▓ │ │          │ │  ░░░░░░  │ │ ▓▓▓▓▓▓▓▓ │
│ ▓ 缩略图 │ │  ＋ 未生成│ │ 生成中 45%│ │ ▓▓▓▓▓▓▓▓ │
│ ▓▓▓▓▓▓▓▓ │ │          │ │  ░░░░░░  │ │ ▓▓▓▓▓▓▓▓ │
├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤
│ 01 · 3.2s│ │ 02 · 2.0s│ │ 03 · 4.5s│ │ 04 · 3.0s│
│ 远景/推轨│ │ 特写/固定│ │ 中景/手持│ │ 特写/固定│
│ 林夏推开…│ │ 门缝里的…│ │ 走廊尽头…│ │ 她数了三…│
│ ✓已选 v2 │ │ ○ 待生成 │ │ ◐ 生成中 │ │ 🔒已锁   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```

- **卡片 = 镜头（unit of type shot）+ 它的候选素材**
- 悬停卡片：`生成图` `生成视频` `重生成` `上传替换` `选版本`
- 一个镜头有多个候选时，卡片底部出现小圆点分页，左右切换选片
- **多选 → 批量生成**：选 8 个镜头 → "为选中镜头各生成 1 张概念图" → 一个父 job + 8 个子 job，进度回到任务坞
- 生成中用**骨架 + 百分比**占位，不弹 toast、不跳页
- 拖拽卡片重排 → `PATCH unit.order_index`
- 右上 `☰` 切列表模式：紧凑表格，适合几十上百个镜头时通读

### 4.5 画布 · 时间线（Timeline）

v1 **不做完整 NLE**，只做"可预览、可微调、可出片"：

```
┌─────────────── 播放器 16:9 / 9:16 ───────────────┐
│                                                   │
└───────────────────────────────────────────────────┘
  ▶  00:12.4 / 01:48.0     [⟲ 重新编译] [🎬 生成成片]

  0s      10s     20s     30s     40s     50s
  ├───────┼───────┼───────┼───────┼───────┤
V │[01][02][ 03  ][04][05][  06  ][07]        │
A │[───── 环境音 ─────][── 环境音2 ──]         │  🔇
配│  [旁白1] [旁白2]      [旁白3]              │
字│  [──][──] [────]      [───]                │
```

- 轨道来自 `TimelineIR.tracks`（video / audio / voice / subtitle）
- v1 支持：**拖动改时长、拖动重排、静音/独奏、音量、点击 clip 跳到对应镜头卡**
- 不支持：多层特效、关键帧曲线编辑（`Keyframe` 结构留着，UI 后置）
- `重新编译` = `POST /timeline/compile`；`生成成片` = `POST /timeline/render` → 任务坞
- 用轻量自绘（div + transform），**不引入时间线库**；xyflow/echarts 该删就删

### 4.6 画布 · 素材（Media）

```
筛选  [全部][图片][视频][音频][参考]   来源[AI生成|上传]  [已使用|未使用]  🔍
```

- 网格，视频悬停自动预览首 3 秒，音频显示波形条
- 选中 → 右侧信息栏：来源 job、prompt、参数、`parent_asset_id` **血缘链**（"由 ref-003 + prompt 生成 → 被镜头 04 使用"）
- 支持拖拽到分镜卡片 / 时间线轨道
- 批量：删除、改归属单元、加标签

> 后端依赖：缩略图接口（BE-7）。现在直接 `<img src={asset.uri}>` 加载原图，几十张就卡。

### 4.7 画布 · 版本（Versions）

左侧版本列表（v1…vN，带 `source` 徽标：AI / 用户 / 任务），右侧并排 diff：

```
v3  AI · 2小时前            v4  用户 · 12分钟前   [恢复到 v3]
─────────────────────      ─────────────────────
  shots[7].duration          shots[7].duration
- 3.2                      + 8.5
  shots[7].camera            shots[7].camera
  "特写"                     "特写"
```

结构化 diff（不是文本 diff），按字段路径对齐。

### 4.8 结构导航（长篇的地基）

```
┌ 迷失月球 ─────────────────┐
│ ◕ 62%  ·  14/28 单元完成   │
├───────────────────────────┤
│ 🔍 搜索        [筛选 ▾]    │
├───────────────────────────┤
│ ◉ 项目总览                 │
│ ▾ 第一卷            ✓ 8/8 │
│   ├ 第1章           ●●●   │
│   ├ 第2章           ●●○   │
│ ▾ 第二卷            ◐ 1/6 │
│   ├ 第7章  ⚡2      ●○○   │  ← ⚡2 = 2 条待处理提案
│   │  ├ 镜头01       ●●●   │
│   │  └ 镜头02       ●○○   │
│   └ 第8章           ○○○   │
├───────────────────────────┤
│ ── 连贯性 ──               │
│ 👤 角色 5   🌍 世界   🎨 风格│
│ 🔒 已锁定 3 项              │
└───────────────────────────┘
```

- **三点完成度环**：`稿件 / 素材 / 成片` 三个小圆点，一眼看出每个单元卡在哪一环
- **虚拟化**（`@tanstack/react-virtual`，需新增）：1000+ 单元不掉帧
- **筛选**：只看未完成 / 只看有提案 / 只看已锁定 / 按 unit_type
- **多选 → 批量交给 Agent**：`Shift` 选 8 个镜头 → 右键"交给 Agent" → 自动填入上下文条
- **拖拽重排 / 改父级** → `PATCH unit`
- **连贯性区**：角色 / 世界 / 风格 圣经的常驻入口。点开是浮层，每项可 `📌 钉到上下文`（钉住后每轮对话自动带上）—— 这是长篇不崩人设的关键

### 4.9 任务坞（Job Dock）

替代"任务是另一个页面"。折叠态一行：

```
▴ 分镜图 2/8 ▓▓▓░░░░░  ·  配音 排队中  ·  ✕ 成片渲染失败      [展开]
```

展开 220px：紧凑列表，每行 `类型 · 目标单元 · 进度 · 耗时 · [取消][重试][跳转结果]`。
点「跳转结果」直接定位到画布上生成出来的那张图 / 那个 clip。

`/jobs` 保留为跨项目全局视图。

### 4.10 项目库首页

去掉"点击新建 → 弹窗填表单"。改为 **prompt-first**：

```
              你想创作什么？
   ┌────────────────────────────────────────────┐
   │ 把一个失踪宇航员的故事写成 5 集悬疑短剧      │
   │                                   [开始 →] │
   └────────────────────────────────────────────┘
   [🎬 短片] [📺 剧集] [🖼 图文] [🎵 MV] [✨ 随意]

   ── 最近 ──────────────────────── 进行中 4 · 已完成 2 ──
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ ▓▓ 封面图 ▓▓ │ │ ▓▓ 封面图 ▓▓ │ │   ＋ 新建     │
   ├──────────────┤ ├──────────────┤ │              │
   │ 迷失月球  ⚡2 │ │ 夏日气泡水    │ │              │
   │ ◕ 62% · 14/28│ │ ◕ 100%       │ │              │
   │ 2h前 AI生成了 │ │ 昨天 已出片   │ │              │
   │ 8 个镜头      │ │              │ │              │
   └──────────────┘ └──────────────┘ └──────────────┘
```

- 输入即创建项目并直接进工作台，Agent 已带着这句话开始工作（当前是"填表单 → 进去 → 再自己开对话"，多了两跳）
- 卡片有 **封面**（首个 render/image 资产）、**进度环**、**待处理提案徽标**、**最近活动一句话**

> 后端依赖：项目列表返回 `cover_asset_id` / `pending_proposal_count` / `last_activity`（BE-10），否则要 N+1 请求。

### 4.11 模型设置

现在是 provider 优先，且要用户手写 `models_json` 裸 JSON（`settings/page.tsx:51`）。改为 **能力优先**：

```
能力                当前使用                      状态
─────────────────────────────────────────────────────
💬 文本生成    claude-opus-5 · Anthropic     ● 正常 42ms  [测试][切换]
🖼 图片生成    未配置                        ○           [配置]
🎬 视频生成    未配置                        ○           [配置]
🔊 语音合成    edge-tts（内置）              ● 正常       [切换]
```

- 配置弹窗按 adapter 给预设模板（OpenAI 兼容 / Anthropic / grok2api），模型列表用表格增删行，不让用户碰 JSON
- 每个渠道一个 **[测试连接]**（BE-8）
- 工作台里能力缺失时的提示直接深链到这里对应那一行

---

## 5. 设计系统整顿

### 5.1 组件库：保留 antd，但收缩职责

**推荐方案（成本最低、收益够）**：

- **保留 antd** 用于 *控件*：Input / Select / Form / Modal / Drawer / Upload / Popconfirm / Tooltip / Progress
- **禁用 antd 的 *容器*类**：Card / Tabs / List / Layout / Table（表格例外：设置页可留）→ 全部用 Tailwind + `--studio-*` 自绘
- **删除 shadcn**：移除 `@import "shadcn/tailwind.css"`、`shadcn` 依赖、`components.json`、以及 `globals.css` 里整段 oklch 变量与 `@theme inline` 映射。当前它只提供了一套没人用的紫色 token，纯粹制造不自洽
- 用 `--studio-*` 反向驱动 antd 主题（`getAntThemeConfig` 已经在做，补全 token 映射即可）

> 备选：全量迁 shadcn/radix。视觉自由度更高，但要重写所有 Form/Modal/Upload，**成本 2-3 周且不产生用户可见价值**，不建议现在做。

### 5.2 Token 收敛

从 ~60 个压到 ~24 个，写进 `docs/design-tokens.md`：

```
表面   bg / surface / surface-raised / surface-hover
描边   line / line-strong
文字   ink / text / muted / faint
主色   action / action-hover / action-fg / action-soft / action-line
语义   success / warning / danger / info
圆角   r-sm 6 / r-md 10 / r-lg 16
阴影   shadow-sm / shadow-md
动效   ease  cubic-bezier(0.16,1,0.3,1)
       dur-fast 120 / dur 180 / dur-slow 280
```

同时清理：删掉 `globals.css:1116` 起那段重复覆盖 `.studio-sidebar-rail` 的代码，只保留一处定义。

### 5.3 视觉方向

**暗色优先**。媒体创作工具里，图片和视频在近黑背景上才准确（现有暗色 `#050606` + 青柠 `#c7f36b` 其实是对的，问题只在亮色被当成了默认）。建议：

- 默认暗色，亮色作为可选
- 主色统一走 `--studio-action`（暗色青柠 / 亮色橄榄绿），**删掉粉色 `--studio-accent`** 的滥用，只保留它做"AI 产出"的语义标记
- 字号梯度固定 5 级：`11 / 12 / 13 / 15 / 20`（当前 10px 出现在正文，太小）

---

## 6. 前端技术架构

### 6.1 服务端状态 → React Query

Provider 已经在了，直接开用。按资源建 query key：

```ts
// web/src/services/queries/keys.ts
export const qk = {
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  units: (pid: string, parent?: string) => ['units', pid, parent ?? 'root'] as const,
  artifacts: (pid: string, unit?: string) => ['artifacts', pid, unit ?? 'all'] as const,
  assets: (pid: string, unit?: string) => ['assets', pid, unit ?? 'all'] as const,
  conversation: (id: string) => ['conversation', id] as const,
  jobs: (pid?: string) => ['jobs', pid ?? 'all'] as const,
}
```

**用精确 `invalidateQueries` 取代全量 `load()`**：

| 操作 | 现在 | 改后 |
|---|---|---|
| 采纳提案 | `load()` → 4 请求 | invalidate `artifacts(pid, unit)` + `project(pid)` |
| 上传素材 | `load()` → 4 请求 | optimistic 插入 `assets(pid, unit)` |
| 发消息 | 6 请求 | optimistic 追加 + SSE 流式，结束时 invalidate `conversation` |

乐观更新覆盖：发消息、采纳/拒绝提案、单元重排、删除素材、选择候选图。

### 6.2 客户端状态 → zustand（只放 UI）

```ts
useWorkspaceStore: {
  selectedUnitId, activeView, panelSizes, dockExpanded,
  composerDraft, composerMode, contextRefs[], pinnedRefs[]
}
```

服务端数据一律不进 zustand，避免现在这种"两份真相"。

### 6.3 流式

```ts
// 对话
new EventSource(`/api/conversations/${id}/stream?...`)
// 事件: step.start | step.done | token | proposal | done | error

// 任务
new EventSource(`/api/jobs/stream?project_id=${pid}`)
// 事件: job.progress | job.event | job.done
```

单例 SSE 管理器，断线指数退避重连，**降级到现有轮询**（保证后端未就绪时 UI 仍可用）。

### 6.4 性能

- 虚拟化：结构树、消息流、素材网格、分镜网格（`@tanstack/react-virtual`）
- 懒加载：timeline / board / versions 视图 `dynamic(() => import(...), { ssr: false })`
- 图片：缩略图 + `loading="lazy"` + `IntersectionObserver` 预加载相邻
- **删除未使用依赖**：`@xyflow/react`、`echarts`、`@assistant-ui/react`、`localforage`、`fflate`、`file-saver`、`copy-to-clipboard`、`axios`、`nanoid`、`motion`（若不做动效）、`@ant-design/pro-components`（只用了 `ProConfigProvider` 一个空壳）→ 预计首屏 JS 降 40%+

### 6.5 目录结构

```
web/src/
  app/(user)/projects/[id]/
    layout.tsx                 # 三栏 shell + 数据预取
    story/page.tsx  board/page.tsx  timeline/page.tsx  media/page.tsx  versions/page.tsx
  features/
    agent/        # 面板、运行轨迹、提案卡、上下文条、composer
    canvas/       # story / board / timeline / media / versions
    structure/    # 树、完成度环、筛选、圣经
    jobs/         # 任务坞
    projects/     # 项目库
    settings/
  services/
    api/          # 按域拆：projects.ts / artifacts.ts / assets.ts / jobs.ts …（现在 522 行一个文件）
    queries/      # keys + hooks
    stream/       # SSE 管理器
  shared/ui/      # 自绘基础件：Surface / Panel / Pill / StatusDot / ProgressRing / EmptyState / Skeleton
```

### 6.6 韧性

- 每个面板一个 `ErrorBoundary` + 重试按钮（一个面板挂了不白屏）
- 骨架屏形状与最终布局一致
- 空状态必须带下一步动作（现在 `Empty description="暂无"` 是死路）
- `aria-live="polite"` 播报 Agent 流式与任务完成
- 全键盘：树上下导航、`Space` 多选、`⌘K`、`Esc` 关浮层

---

## 7. UI 依赖的后端契约

按对 UI 的阻塞程度排序。**BE-1 ~ BE-4 是新 UI 的前置条件**，其余可后补。

| # | 契约 | 阻塞什么 |
|---|---|---|
| **BE-1** | `GET /api/conversations/{id}/stream` (SSE)：`token` / `step.*` / `proposal` / `done` | 流式对话、运行轨迹。**当前最坏 30 分钟无反馈** |
| **BE-2** | `POST /messages` 接受 `context_refs: [{type, id}]`，后端按引用组装上下文，不再全量转储 | 上下文条、长篇不爆 token |
| **BE-3** | `GET /api/jobs/stream?project_id=` (SSE) | 任务坞实时进度，去掉 4s 轮询 |
| **BE-4** | 分页 / 按需：`GET /projects/{id}` 不再返回全部 artifact payload；`units?parent_id=&depth=`；`artifacts?page=`、`assets?page=` | 长篇结构树、素材库 |
| BE-5 | `GET /api/artifact-versions/{a}/diff/{b}` 结构化 diff | 版本视图、提案完整对比 |
| BE-6 | `POST /api/proposals/{id}/accept {op_indices:[]}` | 逐条采纳提案 |
| BE-7 | `GET /api/assets/{id}/thumb?w=`；metadata 带 `width/height/duration` | 素材库、分镜卡片性能 |
| BE-8 | `POST /api/provider-profiles/{id}/test` | 设置页连接测试 |
| BE-9 | `POST /projects/{id}/generate/batch {unit_ids, capability, ...}` → 父 job + N 子 job | 分镜批量生成 |
| BE-10 | 项目列表返回 `cover_asset_id` / `pending_proposal_count` / `last_activity` | 项目库卡片，避免 N+1 |
| **BE-11** | `MediaStore.write_bytes` 应返回相对路径，asset.uri 存 `/media/<relative>` 而不是绝对文件系统路径 | 见下方「P0 期间发现的后端缺陷」 |
| BE-12 | `ProviderPatch` 增加 `models` 字段 | 编辑渠道时无法修改模型列表 |

### P0 期间发现的后端缺陷

改前端时撞上的两个真实 bug，已在前端做了兜底，但根因在后端：

1. **所有图片/视频在界面上都是坏的。**
   `app/store/media_store.py:33` 的 `write_bytes` 返回 `target.as_posix()`——一个**绝对文件系统路径**
   （`D:/WorkSpace/.../data/media/<project>/<uuid>.png`），`app/api/routes/assets.py:57` 原样存进 `asset.uri`，
   前端再直接塞进 `<img src>`。浏览器无法从 http 源加载这种地址。
   同时 `web/next.config.ts` 代理的是 `/outputs/:path*`，而后端真正的媒体路由是 `/media/{project_id}/{path}`
   （`app/api/routes/media.py:6`）——代理指向了一个不存在的路由，真实路由反而没被代理。
   **P0 兜底**：`next.config.ts` 改为代理 `/media/:path*`；`services/api/http.ts` 的 `mediaUrl()` 从绝对路径里
   截出 `data/media/` 之后的部分再拼成 `/media/...`。根治方案是 BE-11，改完可以删掉前端那段兼容分支。

2. **编辑渠道时改模型列表静默失效。**
   `app/api/routes/providers.py:31` 的 `ProviderPatch` 没有 `models` 字段，但设置页一直显示一个可编辑的
   「模型列表（JSON）」输入框。用户改完保存，什么都不会发生。
   **P0 兜底**：编辑态把该字段设为只读并说明原因。根治方案是 BE-12。

**降级策略**：BE-1/BE-3 未就绪时，UI 用现有轮询模拟流式（job 事件已有 `stage` 字段，够拼出轨迹）；BE-6 未就绪时，提案卡显示字段级 diff 但只提供"全部采用"。**UI 改造不必等后端。**

---

## 8. 实施计划

### P0 · 地基（约 1 周）— 不加任何功能

| 任务 | 产出 | 状态 |
|---|---|---|
| 拆 765 行工作台 | `layout.tsx` + 4 个视图 page + features 目录 | ✅ |
| 接入 React Query | 删除所有 `load()`，query keys + 精确 invalidate + 乐观更新 | ✅ |
| zustand 只管 UI 状态 | `useWorkspaceStore`（面板尺寸/折叠/草稿） | ✅ |
| 视图进路由 | `/projects/[id]/{story,media,produce,brief}?unit=` | ✅ |
| 拆 `services/api/server.ts` | `http` + `types` + 按域 7 个文件 | ✅ |
| 设计系统整顿 | 删 shadcn、token 60→24、`globals.css` 1660→约 340 行 | ✅ |
| 删未用依赖 | 移除 18 个零引用包 | ✅ |

> P0 只搬运既有功能。视图定为 story / media / produce / brief 四个——分别对应旧版的
> 「创作 / 素材 / 生成视频 / 创作设定」四个 antd Tab。**board（分镜）在 P2 加入，
> timeline 与 versions 在 P4 加入**，P0 不建空壳路由。

**验收**：发一条消息的请求数 6 → 2；工作台单文件 ≤ 200 行；刷新页面后视图与选中单元不丢；`pnpm build` 产物体积下降 ≥ 30%。

### P1 · Agent 成为主角（约 1.5 周，依赖 BE-1/2）

新 Shell + 舞台自适应 · Agent 面板（运行轨迹 / 上下文条 / 内联提案 / 创作模式）· SSE 流式（带轮询降级）

**验收**：首 token < 2s 可见；任意时刻能看到 Agent 在做哪一步；提案能看到字段级 diff；上下文条显示的内容 = 后端实际收到的上下文。

### P2 · 作品看得见（约 2 周，依赖 BE-7/9）

Story 分体裁渲染 + 块级改写 · **Board 分镜卡片 + 图片/视频生成 + 批量** · Media 素材库 + 血缘

**验收**：能从"一句话"到"一张能看的分镜图"全程不离开工作台；8 个镜头批量生成一次点击完成。

### P3 · 扛住长篇（约 1 周，依赖 BE-4）

虚拟化结构树 + 三点完成度环 + 筛选 + 批量交给 Agent · 圣经面板 + 钉住上下文 · 分页

**验收**：500 单元项目结构树滚动 60fps；单元切换首屏 < 300ms；连续 20 轮对话上下文不超阈值。

### P4 · 出片（约 1.5 周，依赖 BE-5）

时间线视图 + 播放器 + 渲染 · 版本 / diff 视图 · 任务坞

**验收**：能预览、微调、导出成片；能对比任意两个版本并回滚。

### P5 · 打磨（约 1 周）

`⌘K` 命令面板 · 全键盘 · a11y · 空/错/载状态 · 平板适配 · 文案统一

**总计约 8 周**（单人）。P0 是硬前置，P1-P4 之间可并行度较高。

---

## 9. 已确认的决策

1. **组件库**：保留 antd 做控件 + 删掉 shadcn（第 5.1 节）。
2. **视觉基调**：暗色优先，亮色降为可选（第 5.3 节）。
3. **实施顺序**：P0 → P1 → P2 → P3 → P4 → P5，不跳步。

---

*本文覆盖 UI/前端。后端方案（Agent 循环与工具调用、流式、上下文压缩与长篇记忆、任务队列从线程改为可靠队列、媒体 provider 适配、渲染管线）单独出。*
