"use client";

import type { ReactNode } from "react";

import { App as AntdApp, ConfigProvider } from "antd";
import type { ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";

/**
 * antd 收编的顶层 Provider：ConfigProvider + App（message/modal/notification）。
 * feature 代码只从这里拿 useApp，不直接引 antd。
 */
export function AntdProvider({ theme, children }: { theme: ThemeConfig; children: ReactNode }) {
    return (
        <ConfigProvider locale={zhCN} theme={theme}>
            <AntdApp>{children}</AntdApp>
        </ConfigProvider>
    );
}

/** antd App.useApp 的收编出口（message / modal / notification）。 */
export const useApp = AntdApp.useApp;
