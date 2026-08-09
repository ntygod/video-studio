import type { Metadata } from "next";
import Script from "next/script";
import { cookies } from "next/headers";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { AppProviders } from "@/features/app-shell/components/app-providers";
import { buildThemeBootstrapScript, getInitialResolvedTheme, readThemePreferenceFromCookieStore } from "@/shared/lib/theme-preference";
import "antd/dist/reset.css";
import "./globals.css";
import React from "react";

export const metadata: Metadata = {
    title: "Video Studio · 通用创作工作台",
    description: "开放式的 AI 创作系统：任意项目、任意内容单元、任意工作流，AI 协作讨论、提案审批、版本化产物与统一模型配置。",
    icons: {
        icon: "/logo/favicon-32x32.png",
        shortcut: "/logo/favicon-32x32.png",
        apple: "/logo/favicon-32x32.png",
    },
};

export default async function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    const cookieStore = await cookies();
    const initialThemePreference = readThemePreferenceFromCookieStore(cookieStore) ?? "dark";
    const initialResolvedTheme = getInitialResolvedTheme(initialThemePreference);

    return (
        <html
            lang="zh-CN"
            suppressHydrationWarning
            className="font-sans"
            data-theme={initialResolvedTheme}
            data-theme-preference={initialThemePreference}
            style={{ colorScheme: initialResolvedTheme }}
        >
            <body
                style={{
                    fontFamily: '"SF Pro Display","SF Pro Text","PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif',
                }}
            >
                <Script id="theme-script" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: buildThemeBootstrapScript(initialThemePreference) }} />
                <AntdRegistry>
                    <AppProviders initialThemePreference={initialThemePreference} initialResolvedTheme={initialResolvedTheme}>
                        {children}
                    </AppProviders>
                </AntdRegistry>
            </body>
        </html>
    );
}

