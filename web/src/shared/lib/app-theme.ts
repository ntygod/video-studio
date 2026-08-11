import type { ThemeConfig } from "antd";
import { theme as antdTheme } from "antd";

import type { ResolvedTheme } from "@/shared/lib/theme-preference";

/**
 * 设计令牌的 TypeScript 副本。
 * <p>
 * 真正的来源是 app/globals.css 里的 --s-* 变量。antd 的 ConfigProvider 需要在
 * 渲染时拿到具体值，而 SSR 阶段没有 DOM 可读 CSS 变量，因此这里保留一份镜像。
 * 改动任何一侧都要同步另一侧。
 */
type StudioPalette = {
    canvas: string;
    base: string;
    panel: string;
    raised: string;
    overlay: string;
    hairline: string;
    hairlineStrong: string;
    ink: string;
    text: string;
    muted: string;
    faint: string;
    action: string;
    actionHover: string;
    actionEmphasis: string;
    actionForeground: string;
    actionSoft: string;
    success: string;
    warning: string;
    danger: string;
    info: string;
};

const DARK: StudioPalette = {
    canvas: "#0a0a0b",
    base: "#0f0f11",
    panel: "#161619",
    raised: "#202024",
    overlay: "#29292e",
    hairline: "rgba(255,255,255,0.055)",
    hairlineStrong: "rgba(255,255,255,0.10)",
    ink: "#f3f1eb",
    text: "#c8c6c0",
    muted: "#b0aea8",
    faint: "#97979c",
    action: "#ff7540",
    actionHover: "#ff936c",
    actionEmphasis: "#e95f2b",
    actionForeground: "#160b06",
    actionSoft: "rgba(255,117,64,0.16)",
    success: "#61d69c",
    warning: "#f0c869",
    danger: "#ff7d7d",
    info: "#6aaee0",
};

const LIGHT: StudioPalette = {
    canvas: "#f7f6f2",
    base: "#efeee9",
    panel: "#fffefa",
    raised: "#eceae3",
    overlay: "#fffefa",
    hairline: "rgba(15,16,17,0.06)",
    hairlineStrong: "rgba(15,16,17,0.10)",
    ink: "#191918",
    text: "#41413e",
    muted: "#565650",
    faint: "#62625d",
    action: "#b9471c",
    actionHover: "#a63c15",
    actionEmphasis: "#913410",
    actionForeground: "#ffffff",
    actionSoft: "rgba(185,71,28,0.12)",
    success: "#1f7a52",
    warning: "#8a5c00",
    danger: "#b42318",
    info: "#2f678f",
};

/** 主题对应的调色板。 */
export function paletteFor(resolvedTheme: ResolvedTheme): StudioPalette {
    return resolvedTheme === "dark" ? DARK : LIGHT;
}

/**
 * 生成 Ant Design 主题配置。
 * <p>
 * antd 只负责控件（输入、选择、弹窗、上传、表格），容器与布局由 Tailwind +
 * --s-* 自绘，所以这里只需要把控件的表面、描边、文字和主色对齐即可。
 *
 * @param resolvedTheme ResolvedTheme 当前生效主题
 * @return ThemeConfig antd 主题配置
 */
export function getAntThemeConfig(resolvedTheme: ResolvedTheme): ThemeConfig {
    const isDark = resolvedTheme === "dark";
    const p = paletteFor(resolvedTheme);

    return {
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        cssVar: { key: isDark ? "studio-dark" : "studio-light" },
        token: {
            colorPrimary: p.action,
            colorInfo: p.info,
            colorSuccess: p.success,
            colorWarning: p.warning,
            colorError: p.danger,
            colorLink: p.action,
            colorLinkHover: p.actionHover,
            colorLinkActive: p.actionEmphasis,
            colorTextLightSolid: p.actionForeground,
            colorBgLayout: p.base,
            colorBgContainer: p.panel,
            colorBgElevated: p.overlay,
            colorBorder: p.hairlineStrong,
            colorBorderSecondary: p.hairline,
            colorText: p.ink,
            colorTextSecondary: p.text,
            colorTextTertiary: p.muted,
            colorTextQuaternary: p.faint,
            colorFillQuaternary: p.actionSoft,
            colorFillTertiary: p.raised,
            colorSplit: p.hairline,
            borderRadius: 8,
            fontSize: 13,
            // 界面字体统一走 Inter（与 globals.css --font-sans 同链），
            // 避免 antd App 默认的系统字体栈盖掉设计字体。
            fontFamily:
                '"Inter", "PingFang SC", "Noto Sans SC", ui-sans-serif, system-ui, -apple-system, "Microsoft YaHei", sans-serif',
            // antd 默认会把 sm/icon 推导成 10px，低于设计下限，显式提到 12px。
            fontSizeSM: 12,
            fontSizeIcon: 12,
            boxShadow: isDark ? "0 16px 48px rgba(0,0,0,0.45)" : "0 16px 40px rgba(23,26,23,0.10)",
        },
        components: {
            Button: {
                primaryShadow: "none",
                primaryColor: p.actionForeground,
                defaultBg: p.raised,
                defaultBorderColor: p.hairlineStrong,
                defaultColor: p.text,
                defaultHoverBg: p.overlay,
                defaultHoverColor: p.ink,
                defaultHoverBorderColor: p.action,
                borderRadius: 8,
                controlHeight: 32,
            },
            Input: {
                activeBorderColor: p.action,
                activeShadow: `0 0 0 2px ${p.actionSoft}`,
                hoverBorderColor: p.hairlineStrong,
                borderRadius: 8,
                colorBgContainer: p.raised,
            },
            Modal: {
                contentBg: p.overlay,
                headerBg: p.overlay,
                footerBg: p.overlay,
                borderRadiusLG: 14,
            },
            Drawer: {
                colorBgElevated: p.overlay,
            },
            Table: {
                rowSelectedBg: p.actionSoft,
                rowSelectedHoverBg: p.raised,
                headerBg: p.raised,
                headerColor: p.muted,
                borderColor: p.hairline,
            },
            Tag: {
                defaultBg: p.raised,
                defaultColor: p.text,
            },
            Select: {
                optionActiveBg: p.raised,
                optionSelectedBg: p.actionSoft,
                optionSelectedColor: p.ink,
                colorBgContainer: p.raised,
                borderRadius: 8,
            },
            Progress: {
                defaultColor: p.action,
                remainingColor: p.raised,
            },
            Tooltip: {
                colorBgSpotlight: p.overlay,
                colorTextLightSolid: p.ink,
            },
            Popover: {
                colorBgElevated: p.overlay,
            },
            Popconfirm: {
                colorBgElevated: p.overlay,
            },
            Dropdown: {
                colorBgElevated: p.overlay,
            },
            Segmented: {
                trackBg: p.raised,
                itemSelectedBg: p.panel,
                itemSelectedColor: p.ink,
            },
        },
    };
}
