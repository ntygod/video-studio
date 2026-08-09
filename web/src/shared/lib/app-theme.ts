import type { ThemeConfig } from "antd";
import { theme as antdTheme } from "antd";

import type { ResolvedTheme } from "@/shared/lib/theme-preference";

/**
 * 设计令牌的 TypeScript 副本。
 * <p>
 * 真正的来源是 app/globals.css 里的 --studio-* 变量。antd 的 ConfigProvider 需要在
 * 渲染时拿到具体值，而 SSR 阶段没有 DOM 可读 CSS 变量，因此这里保留一份镜像。
 * 改动任何一侧都要同步另一侧——app-theme.test.ts 会校验两个主题的结构一致性，
 * 但校验不了取值是否与 CSS 同步。
 */
type StudioPalette = {
    bg: string;
    surface: string;
    surfaceRaised: string;
    surfaceHover: string;
    line: string;
    lineStrong: string;
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
    bg: "#050606",
    surface: "#0c0e0d",
    surfaceRaised: "#121512",
    surfaceHover: "#181c18",
    line: "#242824",
    lineStrong: "#363c36",
    ink: "#f3f6f0",
    text: "#c2c9c0",
    muted: "#858d84",
    faint: "#727a71",
    action: "#c7f36b",
    actionHover: "#d6ff82",
    actionEmphasis: "#afda54",
    actionForeground: "#11170a",
    actionSoft: "rgba(199,243,107,0.16)",
    success: "#5ed69b",
    warning: "#f3c969",
    danger: "#ff7c7c",
    info: "#75b7f5",
};

const LIGHT: StudioPalette = {
    bg: "#f4f5f2",
    surface: "#ffffff",
    surfaceRaised: "#ecefe9",
    surfaceHover: "#e5e9e2",
    line: "#dce1da",
    lineStrong: "#c7cec4",
    ink: "#171a17",
    text: "#394037",
    muted: "#596157",
    faint: "#687066",
    action: "#526f1e",
    actionHover: "#648625",
    actionEmphasis: "#405718",
    actionForeground: "#ffffff",
    actionSoft: "rgba(82,111,30,0.12)",
    success: "#1f7a4d",
    warning: "#8a5c00",
    danger: "#b42318",
    info: "#28679b",
};

/** 主题对应的调色板。 */
export function paletteFor(resolvedTheme: ResolvedTheme): StudioPalette {
    return resolvedTheme === "dark" ? DARK : LIGHT;
}

/**
 * 生成 Ant Design 主题配置。
 * <p>
 * antd 只负责控件（输入、选择、弹窗、上传、表格），容器与布局由 Tailwind +
 * --studio-* 自绘，所以这里只需要把控件的表面、描边、文字和主色对齐即可。
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
            colorBgLayout: p.bg,
            colorBgContainer: p.surface,
            colorBgElevated: p.surfaceRaised,
            colorBorder: p.lineStrong,
            colorBorderSecondary: p.line,
            colorText: p.ink,
            colorTextSecondary: p.text,
            colorTextTertiary: p.muted,
            colorTextQuaternary: p.faint,
            colorFillQuaternary: p.actionSoft,
            colorFillTertiary: p.surfaceRaised,
            colorSplit: p.line,
            borderRadius: 8,
            fontSize: 13,
            boxShadow: isDark ? "0 12px 32px rgba(0,0,0,0.36)" : "0 8px 24px rgba(23,26,23,0.08)",
        },
        components: {
            Button: {
                primaryShadow: "none",
                primaryColor: p.actionForeground,
                defaultBg: p.surface,
                defaultBorderColor: p.lineStrong,
                defaultColor: p.text,
                defaultHoverBg: p.surfaceHover,
                defaultHoverColor: p.ink,
                defaultHoverBorderColor: p.action,
                borderRadius: 8,
                controlHeight: 34,
            },
            Input: {
                activeBorderColor: p.action,
                activeShadow: `0 0 0 2px ${p.actionSoft}`,
                hoverBorderColor: p.lineStrong,
                borderRadius: 8,
                colorBgContainer: p.surface,
            },
            Modal: {
                contentBg: p.surface,
                headerBg: p.surface,
                footerBg: p.surface,
                borderRadiusLG: 12,
            },
            Drawer: {
                colorBgElevated: p.surface,
            },
            Table: {
                rowSelectedBg: p.actionSoft,
                rowSelectedHoverBg: p.surfaceHover,
                headerBg: p.surfaceRaised,
                headerColor: p.muted,
                borderColor: p.line,
            },
            Tag: {
                defaultBg: p.surfaceRaised,
                defaultColor: p.text,
            },
            Select: {
                optionActiveBg: p.surfaceRaised,
                optionSelectedBg: p.actionSoft,
                optionSelectedColor: p.ink,
            },
            Progress: {
                defaultColor: p.action,
                remainingColor: p.surfaceRaised,
            },
            Tooltip: {
                colorBgSpotlight: p.surfaceRaised,
                colorTextLightSolid: p.ink,
            },
        },
    };
}
