"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "antd";
import { RotateCw, TriangleAlert } from "lucide-react";

/**
 * 面板级错误提示。
 *
 * @param title string 标题
 * @param message string | undefined 错误详情
 * @param onRetry (() => void) | undefined 重试回调
 */
export function ErrorPanel({ title, message, onRetry }: { title: string; message?: string; onRetry?: () => void }) {
    return (
        <div className="flex h-full min-h-[200px] flex-col items-center justify-center px-6 text-center">
            <TriangleAlert className="size-6 text-[var(--studio-danger)]" />
            <div className="mt-3 text-sm font-medium text-[var(--studio-ink)]">{title}</div>
            {message ? <p className="mt-1.5 max-w-md text-xs leading-5 text-[var(--studio-muted)]">{message}</p> : null}
            {onRetry ? (
                <Button className="mt-4" size="small" icon={<RotateCw className="size-3.5" />} onClick={onRetry}>
                    重试
                </Button>
            ) : null}
        </div>
    );
}

type BoundaryProps = { children: ReactNode; title?: string };
type BoundaryState = { error: Error | null };

/**
 * 面板级错误边界。
 * <p>
 * 每个面板包一层，一个面板崩溃不会让整个工作台白屏。
 */
export class PanelErrorBoundary extends Component<BoundaryProps, BoundaryState> {
    state: BoundaryState = { error: null };

    static getDerivedStateFromError(error: Error): BoundaryState {
        return { error };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error("[面板渲染失败]", error, info.componentStack);
    }

    render() {
        if (this.state.error) {
            return (
                <ErrorPanel
                    title={this.props.title || "这个面板出错了"}
                    message={this.state.error.message}
                    onRetry={() => this.setState({ error: null })}
                />
            );
        }
        return this.props.children;
    }
}
