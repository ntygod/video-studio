# UI 精细化方案（视觉与手感）

> 上游：`docs/ui-redesign.md` 解决的是**信息架构**（什么放在哪），已落地。
> 本文解决的是**视觉工艺**（看起来是否精致），这是另一条轴。
>
> 只谈 UI 呈现层，不改信息架构、不改后端。
>
> 状态：**已定稿（2026-08-10）**。三处决策已锁定：
> 强调色 `#b8e05f`（保留青柠、降饱和）、界面字体 Inter（自托管）、C3 一次全改。见 §7。

---

## 1. 诊断：粗糙不是审美问题，是系统缺了一层

先给证据，不是感觉。

### 1.1 有令牌，但没有组件层

`docs/design-tokens.md` 定义了 24 个令牌和"antd 只做控件、容器自绘"的规则。
但**没有提供容器**，于是每个人各画各的：

| 现象 | 数量 | 证据 |
|---|---|---|
| 完全相同的 `rounded-lg border border-line bg-surface` 手抄 | **16 处 / 12 文件** | `grep` 全仓库 |
| `text-[10px]`——低于文档规定的 11px 下限 | **41 处 / 20 文件** | 同上 |
| 引用了**根本不存在**的令牌 | 2 处 | `--studio-shadow-md`（`shot-card.tsx:59`）、`--studio-danger-soft`（`run-trace.tsx:48`） |

那两个幽灵令牌意味着：分镜卡的 hover 阴影**没有效果**，失败步骤的红底**是透明的**。
不是写错了一次，而是**没有任何机制阻止写错**。

> 结论：不需要更多令牌。需要一层**把决策封装掉的组件**，让"画错"在物理上不可能。

### 1.2 没有排版身份

`globals.css:18-32` 用 `@font-face` 声明了 Bricolage Grotesque 和 Syne 两套字体，
`layout.tsx:41` 却把 body 的 `fontFamily` 写死成 `SF Pro / PingFang SC`。

**两个 woff2 被下载，零处使用。** 界面上没有任何字体识别度，
全部是 10–13px 的系统无衬线，中英文混排也没有做过对齐调校。

### 1.3 只有一种深度

现在整个界面只有一种材质表达：`1px 边框 + 一个表面色`。
而暗色下 `--studio-line: #242824` 压在 `--studio-surface: #0c0e0d` 上，
明度差不到 8 点——**边框看不清，但每个东西都有边框**。

结果是：容器、卡片、输入框、chip、日志行长得一模一样，
用户无法通过视觉判断"什么可点、什么是背景、什么更重要"。

### 1.4 底色有绿味

`#0c0e0d` 的 G 通道高于 R 和 B。整个 chrome 带一层淡绿。
对一个**要靠肉眼判断生成图片色彩**的工具来说，这是硬伤——
参考图和成片的颜色会被周围的绿味推着走。

### 1.5 antd 与自绘表面互相打架

`shot-card.tsx:94` 这种写法遍布：

```tsx
<Button size="small" type="text" className="!text-white" icon={...} />
```

在黑色蒙层上用 `!important` 掰 antd 的颜色。`<Checkbox>` 直接浮在缩略图上。
控件的圆角、高度、内边距全部是 antd 的，和周围自绘的容器不在一个体系里。

### 1.6 动效是装饰性的

全局只有一个 `chat-msg-in` 淡入。真正需要动效的地方——
面板开合、流式光标、任务进度、乐观更新落定、列表重排——**都是瞬变**。

---

## 2. 新的视觉系统

### 2.1 材质与深度（最大的一处改动）

**放弃"到处画边框"，改用表面层级 + 极细分隔线。**
暗色 UI 里"廉价 / 高级"最大的区别就在这一点。

真中性，去掉绿味：

```css
html[data-theme="dark"] {
  --s-canvas:  #0a0a0b;   /* 最深：媒体井、播放器、日志。让画面自己发光 */
  --s-base:    #0f1011;   /* 页面底 */
  --s-panel:   #151618;   /* chrome：侧栏、顶栏、卡片 */
  --s-raised:  #1c1e21;   /* 输入框、hover、嵌套块 */
  --s-overlay: #232629;   /* 浮层：菜单、气泡、tooltip */

  /* 分隔线不再是"颜色"，而是半透明白，随底色自动适配 */
  --hairline:        rgba(255,255,255,0.055);  /* 内部分隔 */
  --hairline-strong: rgba(255,255,255,0.10);   /* 卡片外沿、控件边 */

  /* 暗色下阴影几乎不可见，靠"顶部高光"造立体感 */
  --lift: inset 0 1px 0 rgba(255,255,255,0.045);
}
```

三条规则：

1. **媒体永远坐在最深的表面上**（`--s-canvas`），不要给缩略图加边框——用底色反差托它
2. **同层不画线**。只有跨层级才需要 hairline
3. **卡片靠 `--s-panel` + `--lift` 浮起来**，不靠边框

浅色主题同理，但反过来：媒体井用最浅的白，chrome 用极淡的灰。

### 2.2 排版

**先把已经下载的字体用起来，并且分工明确。**

| 角色 | 字体 | 用在哪 |
|---|---|---|
| 界面 | Inter（已定，自托管可变字重） | 所有 UI 文本、控件、表格 |
| 展示 | Syne（已下载） | Wordmark、项目标题、空状态大标题、里程碑数字 |
| 等宽 | JetBrains Mono / ui-monospace | 工具名、id、时长、token 计数、日志 |
| 中文 | PingFang SC / Noto Sans SC | 与 Inter 组成 fallback 链 |

> Bricolage Grotesque 删除——它和 Syne 定位重叠，留一个展示字体就够。
> Inter 通过 `@fontsource-variable/inter` 自托管 woff2 子集（约 100KB），不依赖运行时外网；字重只取 400–600。

**尺度换成有对比的**（现在 10/11/12/13 四档挤在一起，等于没有层级）：

| Token | 字号/行高 | 字重 | 用途 |
|---|---|---|---|
| `display` | 28 / 1.15 | 600 | 空状态、项目库主标题（Syne） |
| `title` | 19 / 1.3 | 600 | 页面与面板标题 |
| `heading` | 15 / 1.4 | 600 | 区块标题 |
| `body` | 13.5 / 1.55 | 400 | 正文、消息、控件 |
| `label` | 12 / 1.4 | 500 | 次要文本、面包屑 |
| `caption` | 11 / 1.35 | 500 | 元信息、时间戳 |
| `mono-sm` | 11.5 / 1.4 | 450 | 工具名、时长、id |

**41 处 `text-[10px]` 全部上提到 `caption`(11px) 或 `mono-sm`。**
10px 在 1x 屏上抗锯齿后已经开始糊，是"廉价感"的主要来源之一。

另外两条：

- 所有数字（时长、进度、计数、token）加 `font-variant-numeric: tabular-nums`，跳动时不会左右晃
- 中文正文行高比英文再放宽一档（1.65），现在 1.4 的中文段落挤得读不动

### 2.3 色彩克制

现在 `--studio-action`（青柠 `#c7f36b`）同时承担：主按钮填充、激活导航、焦点环、
加载动画、进度条、选中态、链接色。**在一个媒体工具里，界面比内容还抢眼。**

改为**默认单色，强调色只留三处**：

| 允许用强调色 | 其余一律用中性 |
|---|---|
| 1. 主操作按钮（一屏最多一个） | 次级按钮 = `--s-raised` + hairline |
| 2. 当前选中项的左侧 2px 指示条 | 激活导航 = 提亮文字 + `--s-raised` 底 |
| 3. 焦点环 | 进度条 = `--ink` 单色；加载动画 = `--muted` |

强调色定为降一档饱和的青柠 `#b8e05f`（`#c7f36b` 废弃），纯青柠在近黑上会晕。
语义色（成功/警告/危险/信息）**只用于文字和 1px 描边，不做大面积填充**。

> 这条改完，界面会立刻"安静"下来，用户的眼睛会落到图片和视频上——这才是产品要的。

### 2.4 圆角、间距、密度

```
圆角： --r-xs 4（媒体缩略图、chip）
      --r-sm 6（控件、按钮、输入框）
      --r-md 10（卡片、面板）
      --r-lg 14（浮层、模态）

间距： 4px 基线网格，只允许 4 / 8 / 12 / 16 / 24 / 32 / 48

密度： chrome 区（顶栏/侧栏/工具条）  行高 28-32px，紧
      content 区（故事/设定/表单）    行高 36-40px，松
      canvas 区（分镜/素材/时间线）   由内容驱动，chrome 最小化
```

现在的问题是三个区用同一套密度，导致工具条不够紧、正文不够松。

### 2.5 动效：只做功能性的

删掉纯装饰的淡入，补上这六处**真正降低认知负担**的：

| 场景 | 动效 | 时长 |
|---|---|---|
| 面板开合 / 折叠 | 宽度 + 透明度，`--ease-out` | 220ms |
| 流式输出 | 末尾 2px 光标呼吸，文字不做逐字动画（会晕） | 1.1s 循环 |
| 乐观更新落定 | 从 60% 透明度 → 100%，不位移 | 160ms |
| 分镜卡生成中 | 表面扫过一道 shimmer + 环形进度 | 1.6s 循环 |
| 列表重排 / 删除 | FLIP 位移 | 200ms |
| 步骤完成 | 状态点 scale 1→1.25→1 | 240ms |

统一缓动：`--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`（已有）、
新增 `--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1)` 给双向动画。

---

## 3. 组件层：让"画错"不可能

**这是本方案的核心交付物。** 新建 `web/src/shared/ui/`，把上面所有决策封装进去，
然后**用 lint 禁止 feature 代码里出现裸的 `rounded-* border bg-[var(--s-*)]`**。

### 3.1 基础件清单（14 个）

```
surface.tsx      <Surface level="canvas|panel|raised|overlay" inset? lift?>
card.tsx         <Card interactive? selected? media?>   ← 取代那 16 处手抄
stack.tsx        <Stack gap="1|2|3|4|6|8" dir row|col>  ← 强制走间距梯度
text.tsx         <Text as variant="display|title|heading|body|label|caption|mono">
divider.tsx      <Divider strong?>                      ← 唯一允许画线的地方
field.tsx        <Field label hint error>{control}</Field>
button.tsx       <Button variant="primary|secondary|ghost|danger" size>
icon-button.tsx  <IconButton label>                     ← 强制 aria-label
chip.tsx         <Chip tone removable onRemove>
status-dot.tsx   <StatusDot tone pulse>                （已有，纳入体系）
progress.tsx     <Progress value indeterminate>
skeleton.tsx     <Skeleton variant="text|media|card">
media-frame.tsx  <MediaFrame ratio fit checkerboard>    ← 媒体统一入口
empty-state.tsx  <EmptyState art title description action>（已有，重做视觉）
```

### 3.2 强制手段

`eslint.config.mjs` 增加规则（配合 `eslint-plugin-tailwindcss` 或自定义）：

```js
// 禁止在 features/ 下手写容器样式
'no-restricted-syntax': [{
  selector: 'Literal[value=/rounded-(md|lg|xl).*border.*bg-\\[var\\(--s-/]',
  message: '容器请用 <Surface> / <Card>，不要手写。见 docs/ui-craft.md §3',
}]
```

以及一个 CI 脚本：**扫描 `var(--...)` 引用，与 `globals.css` 定义做 diff，
有幽灵令牌就 fail**——这次那两个就不会漏进来。

---

## 4. 关键界面重做

### 4.1 分镜卡（最能体现"媒体优先"）

现在：`aspect-video` 灰块 + 边框 + 底部 2.5 内边距的文字堆。
问题：媒体被边框圈住、编号是黑色药丸、操作条是纯黑半透明、"生成中…"是灰蒙层。

```
┌──────────────────────────┐   ← 无边框。卡片 = --s-panel + --lift
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│   媒体出血到卡片边缘，坐在 --s-canvas 上
│▓▓▓▓  媒体铺满  ▓▓▓▓▓▓▓▓▓▓│   圆角 --r-xs，透明图垫棋盘格
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│ 01              ●●○      │   ← 编号：mono-sm，无背景，混合模式提亮
│                          │      候选点：右下，hover 才升起
├──────────────────────────┤   ← hairline，不是 border
│ 林夏推开门          3.2s │   ← body / mono-sm tabular
│ 远景 · 推轨              │   ← caption，--muted
└──────────────────────────┘
   hover：整卡 lift 提升 + 底部操作条从下缘滑入（220ms）
   生成中：媒体区 shimmer + 中央环形进度，不盖灰蒙层
   已选中：左侧 2px 强调色指示条，不改边框颜色
```

关键改动：
- 媒体**没有边框**，靠 `--s-canvas` 反差
- 操作按钮用 `<IconButton>`，颜色走 token，不再 `!text-white`
- Checkbox 换成整卡点击 + 左上角出现的自绘勾选圈（antd Checkbox 浮在图上很脏）
- 生成中是 **shimmer + 进度环**，不是"生成中…"四个字

### 4.2 运行轨迹

现在：11px 文字 + 10px mono + 10px 时长，三个尺寸几乎一样，读不出结构。

```
▾ 运行轨迹  ·  4 步  ·  2.4s                        ← label / mono tabular
  ✓  read_unit        第7章 · 剧本 v3          0.2s
  ✓  read_bible       角色 林夏 / 陈默          0.1s
  ◐  generate_media   概念图 3/12         ▓▓▓░░ 
  ○  propose_change
     └ 工具名 mono-sm --ink ／ 摘要 body --muted ／ 耗时 mono-sm --faint 右对齐
     └ 失败行：左侧 2px --danger 竖条 + 文字变 --danger，不做红色底
```

- 三列对齐（状态 / 工具名 / 摘要 / 耗时），不是挤成一行
- 进行中的步骤显示内联进度，而不是只有一个转圈
- 幽灵令牌 `--studio-danger-soft` 的红底直接取消，改左侧竖条

### 4.3 空状态

现在是虚线框 + 一行字。改为：

```
        ╭─────────╮
        │  ◵ ◷ ◶  │      ← 与场景相关的极简线条图形（SVG，非插画）
        ╰─────────╯
       还没有分镜                 ← display 28px Syne
   让 AI 根据第7章的剧本            ← body --muted，最多两行
   生成一组镜头，或者自己添加
        ┌──────────────┐
        │ ✨ 让 AI 生成 │        ← 唯一的主按钮
        └──────────────┘
          或 手动添加镜头          ← ghost 文字按钮
```

虚线框全部去掉——虚线是"占位符"的语言，不是"起点"的语言。

### 4.4 项目库

现在卡片是 `border + surface + 图标方块`。改为**封面优先**：

```
┌────────────────┐  ┌────────────────┐
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │                │   ← 有成片/图：封面铺满 16:9
│▓▓▓ 封面 ▓▓▓▓▓▓▓│  │   ◵            │   ← 无封面：--s-canvas + 极淡字母标记
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │                │
├────────────────┤  ├────────────────┤
│ 迷失月球    ⚡2 │  │ 夏日气泡水      │   ← heading + 提案角标
│ ◕ 62% · 14/28  │  │ ◕ 100% 已出片   │   ← caption tabular
│ 2h前 · 生成8镜头│  │ 昨天           │
└────────────────┘  └────────────────┘
```

---

## 5. antd 收编

现在 antd 控件直接散落在 feature 代码里，靠 `!important` 打补丁。

**规则：feature 代码不允许 `import ... from "antd"`。**
只有 `shared/ui/` 可以，且必须包一层：

| 我们的组件 | 内部实现 | 收敛掉什么 |
|---|---|---|
| `<Button>` | antd Button | 高度 32、圆角 `--r-sm`、字重 500、去掉 antd 波纹 |
| `<Input>` `<Textarea>` | antd Input | 背景 `--s-raised`、focus 环走我们的 token |
| `<Select>` | antd Select | 浮层背景 `--s-overlay`、选项高度 32 |
| `<Modal>` `<Drawer>` | antd | 圆角 `--r-lg`、头部无分隔线、遮罩 `rgba(0,0,0,0.6)` |
| `<Checkbox>` | **自绘** | antd 的方框在媒体上太脏 |
| `<Tooltip>` | antd | 背景 `--s-overlay`、caption 字号、延迟 400ms |
| `<Popconfirm>` | antd | 同上 |
| `<Table>` | antd | 仅设置页使用，其余场景禁止 |

`app-theme.ts` 里的 antd token 同步换成新的 `--s-*` 值。

---

## 6. 执行计划

| 阶段 | 内容 | 工期 | 可验收 |
|---|---|---|---|
| **C1** | 新令牌集（`--s-*` / 排版 / 圆角 / 间距 / 动效），改写 `globals.css` 与 `app-theme.ts`；接入 Inter（自托管 woff2 子集）；删 Bricolage | 1 天 | 幽灵令牌扫描脚本通过；两套主题下截图对比 |
| **C2** | 14 个 primitives + ESLint 规则 + CI 令牌扫描 | 2 天 | `shared/ui` 有 Storybook 式预览页；lint 能拦住裸容器 |
| **C3** | 用 primitives 重写全部 feature 组件（约 35 个文件，**一次全改**，不分批），消灭 16 处手抄容器与 41 处 10px | 3 天 | `grep 'text-\[10px\]'` = 0；`grep 'rounded-lg border'` = 0 |
| **C4** | 四个关键界面重做（分镜卡 / 运行轨迹 / 空状态 / 项目库）+ MediaFrame | 2 天 | 与 §4 线框一致 |
| **C5** | 动效六件套 + 骨架屏对齐真实布局 | 1.5 天 | 面板开合、生成中、重排都有过渡 |
| **C6** | 暗/亮双主题逐屏校对、对比度检查（AA）、1x/2x 屏检查 | 1 天 | 所有文字对比度 ≥ 4.5:1；无 10px |

**合计约 10.5 天。** C1→C2 是硬前置，C3 之后每一步都能单独看到效果。

### 量化验收

```bash
# 幽灵令牌必须为 0
node scripts/check-tokens.mjs

# 违规字号必须为 0
grep -r 'text-\[10px\]' web/src | wc -l        # → 0

# 手抄容器必须为 0
grep -rE 'rounded-(md|lg) border.*bg-\[var' web/src/features | wc -l   # → 0

# feature 代码不得直接引 antd
grep -r 'from "antd"' web/src/features | wc -l  # → 0
```

---

## 7. 决策记录（2026-08-10 定稿）

| 决策 | 结论 | 理由 |
|---|---|---|
| 强调色 | 保留青柠，降饱和为 `#b8e05f`，只允许出现在 §2.3 的三处 | 品牌延续性最好、改动风险最低（委托实施者选定）；纯青柠在近黑上会晕 |
| 界面字体 | 新增 Inter（可变字重，自托管 woff2 子集，字重 400–600），中文回退 PingFang SC / Noto Sans SC | 有识别度、中文混排可控、不依赖运行时外网 |
| 改造范围 | C3 一次全改（约 35 个文件），不分批 | 避免新旧混杂期，视觉一致性优先 |

> 三条决策已分别写入 §2.2、§2.3、§6，正文不再以"建议 / 待定"形式出现。
> 后续如需调整强调色方向（例如冷白 + 只在关键处用色），只改 token 与 §2.3，不影响组件层。
