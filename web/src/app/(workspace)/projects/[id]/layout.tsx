"use client";

import { Suspense, type ReactNode } from "react";

import { WorkspaceShell } from "@/features/workspace/components/workspace-shell";
import { Spin } from "@/shared/ui";

/**
 * 项目工作台布局。
 * <p>
 * 刻意不复用 (user) 组的 AppShell：项目内的横向空间应该全部留给创作，
 * 全局导航退到顶栏的返回链接与设置入口。
 * <p>
 * Suspense 是必需的：工作台通过 useSearchParams 读取 ?unit=，
 * 没有边界时 Next 在预渲染阶段会直接报错。
 */
export default function ProjectWorkspaceLayout({ children }: { children: ReactNode }) {
    return (
        <Suspense
            fallback={
                <div className="flex h-dvh items-center justify-center">
                    <Spin size="large" />
                </div>
            }
        >
            <WorkspaceShell>{children}</WorkspaceShell>
        </Suspense>
    );
}
