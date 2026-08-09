# 设计令牌

唯一来源：`web/src/app/globals.css`。
`web/src/shared/lib/app-theme.ts` 保留一份 TS 镜像给 antd 的 ConfigProvider（SSR 阶段读不到 CSS 变量），**改一侧必须同步另一侧**。

组件库分工：**antd 只做控件**（Input / Select / Form / Modal / Drawer / Upload / Popconfirm / Tooltip / Progress / Table / Tag / Button）；
**容器、布局、卡片一律 Tailwind + `--studio-*` 自绘**。不要使用 antd 的 Card / Tabs / List / Layout。

---

## 表面

从底到上三层。同一屏里不要超过三层，再深就说明层级设计有问题。

| 令牌 | 暗色 | 浅色 | 用途 |
|---|---|---|---|
| `--studio-bg` | `#050606` | `#f4f5f2` | 页面底色、日志区 |
| `--studio-surface` | `#0c0e0d` | `#ffffff` | 面板、卡片、侧栏 |
| `--studio-surface-raised` | `#121512` | `#ecefe9` | 输入框内层、tab 槽、次级块 |
| `--studio-surface-hover` | `#181c18` | `#e5e9e2` | 悬停态 |

## 描边

| 令牌 | 暗色 | 浅色 | 用途 |
|---|---|---|---|
| `--studio-line` | `#242824` | `#dce1da` | 默认分隔与边框 |
| `--studio-line-strong` | `#363c36` | `#c7cec4` | 控件边框、虚线空态 |

## 文字

四级，由强到弱。**正文不要用 `faint`**——它只给元信息。

| 令牌 | 暗色 | 浅色 | 用途 |
|---|---|---|---|
| `--studio-ink` | `#f3f6f0` | `#171a17` | 标题、主要内容 |
| `--studio-text` | `#c2c9c0` | `#394037` | 正文 |
| `--studio-muted` | `#858d84` | `#596157` | 说明、次要 |
| `--studio-faint` | `#727a71` | `#687066` | 时间戳、类型标签、计数 |

## 主操作色

全局**唯一**的强调色。旧版还有一个粉色 `--studio-accent` 被到处滥用，已删除。

| 令牌 | 暗色 | 浅色 |
|---|---|---|
| `--studio-action` | `#c7f36b` | `#526f1e` |
| `--studio-action-hover` | `#d6ff82` | `#648625` |
| `--studio-action-emphasis` | `#afda54` | `#405718` |
| `--studio-action-foreground` | `#11170a` | `#ffffff` |
| `--studio-action-soft` | 16% 透明 | 12% 透明 |
| `--studio-action-line` | 36% 透明 | 32% 透明 |

`-foreground` 是压在 action 底色上的文字色。暗色主色是亮青柠，所以前景是深色——**不要写死 `text-white`**。

## 语义色

| 令牌 | 暗色 | 浅色 |
|---|---|---|
| `--studio-success` | `#5ed69b` | `#1f7a4d` |
| `--studio-warning` | `#f3c969` | `#8a5c00` |
| `--studio-danger` | `#ff7c7c` | `#b42318` |
| `--studio-info` | `#75b7f5` | `#28679b` |

## 圆角 / 阴影 / 动效

| 令牌 | 值 | 用途 |
|---|---|---|
| `--studio-r-sm` | 6px | 小按钮、树节点、chip |
| `--studio-r-md` | 10px | 卡片、面板 |
| `--studio-r-lg` | 16px | 大容器、弹层 |
| `--studio-shadow-sm` | 细 | 选中态、浮起的 tab |
| `--studio-shadow` | 深 | 弹层、抽屉 |
| `--studio-ease` | `cubic-bezier(0.16,1,0.3,1)` | 全站唯一缓动 |
| `--studio-dur` | 180ms | 默认时长 |

`prefers-reduced-motion: reduce` 时全站动画统一降到 0.01ms，在 `globals.css` 末尾一处生效，组件不需要各自处理。

---

## 字号

**只允许这五档**，组件里直接写 `text-[Npx]`：

| 尺寸 | 用途 |
|---|---|
| `11px` | 辅助说明、时间戳、计数 |
| `12px` | 次要文本、面包屑、日志 |
| `13px` | 正文、控件文字、消息气泡 |
| `15px` | 区块小标题 |
| `20px` | 页面标题 |

旧代码里 `text-[10px]` 出现在正文位置，太小，已全部提到 11px。

---

## 焦点

`:focus-visible` 在 `@layer base` 里统一设为 `2px solid var(--studio-action-line)` + `2px` 偏移。
**组件不要再自己写 outline**——重复定义正是旧 `globals.css` 膨胀到 1660 行的原因之一。

---

## 已删除的东西

P0 清理掉的，不要再引入：

- **shadcn 那套 oklch 变量**（`--background` / `--primary` / `--sidebar-*` / `--chart-*` 等约 40 个）与 `@theme inline` 的全量映射。它提供的是一套紫色系 token，和 `--studio-*` 的橄榄绿/青柠并存，导致视觉不自洽且没人真正使用。
- `--studio-glass` / `--studio-glass-strong` / `--studio-panel` / `--studio-panel-solid` / `--studio-surface-soft` / `--studio-rail`：浅色下**全部等于 `#ffffff`**，纯冗余。统一到 `--studio-surface`。
- `--studio-primary-*`：`--studio-action-*` 的别名，二选一。
- `--studio-accent-*`（粉色）、`--studio-brand-middle`、`--studio-brand-glow`、`--studio-brand-shine*`。
- `.creation-composer-*` 全家（约 200 行，含大量 `!important` 覆写 antd）、`.card-active`、`.input-dark`、`.prompt-filter-tag`、`.canvas-*`、`.studio-toolbar`、`.hover-scrollbar*`、`.studio-skeleton`、`.hero-wordmark-*`、`.bg-ambient-glow`。
- 重复定义：`.studio-sidebar-rail` 曾在 `:585` 和 `:1116` 各写一遍，后者整体覆盖前者。现在只有一处。
