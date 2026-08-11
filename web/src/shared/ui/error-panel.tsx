"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { RotateCw, TriangleAlert } from "lucide-react";

import { Button } from "@/shared/ui/button";
import { Stack } from "@/shared/ui/stack";
import { Text } from "@/shared/ui/text";

/**
 * 面板级错误提示。
 *
 * @param title string 标题
 * @param message string | undefined 错误详情
 * @param onRetry (() => void) | undefined 重试回调
 */
export function ErrorPanel({ title, message, onRetry }: { title: string; message?: string; onRetry?: () => void }) {
    return (
        <Stack dir="col" align="center" justify="center" gap="3" className="h-full min-h-[200px] px-6 text-center">
            <TriangleAlert className="size-6 text-[var(--s-danger)]" />
            <Text as="div" variant="heading" tone="ink">
                {title}
            </Text>
            {message ? (
                <Text as="p" variant="body" tone="muted" className="max-w-md">
                    {message}
                </Text>
            ) : null}
            {onRetry ? (
                <Button className="mt-2" variant="secondary" size="sm" icon={<RotateCw className="size-3.5" />} onClick={onRetry}>
                    重试
                </Button>
            ) : null}
        </Stack>
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
