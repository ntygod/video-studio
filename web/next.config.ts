import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

const localServerUrl = process.env.NEXT_PUBLIC_SERVER_URL?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8765";

export default function nextConfig(phase: string): NextConfig {
    const isDev = phase === PHASE_DEVELOPMENT_SERVER;

    return {
        output: "standalone",
        poweredByHeader: false,
        allowedDevOrigins: isDev ? ["*.*.*.*"] : [],
        typescript: {
            ignoreBuildErrors: true,
        },
        env: {
            NEXT_PUBLIC_APP_VERSION: process.env.NEXT_PUBLIC_APP_VERSION || "dev",
        },
        async headers() {
            return [
                {
                    source: "/:path*",
                    headers: [
                        { key: "X-Content-Type-Options", value: "nosniff" },
                        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
                    ],
                },
            ];
        },
        async rewrites() {
            return [
                { source: "/api/:path*", destination: localServerUrl + "/api/:path*" },
                // 素材文件由后端的 /media 路由提供，见 app/api/routes/media.py。
                // 旧配置代理的是 /outputs，而后端并没有这个路由，导致所有图片和视频都加载不出来。
                { source: "/media/:path*", destination: localServerUrl + "/media/:path*" },
            ];
        },
    };
}

