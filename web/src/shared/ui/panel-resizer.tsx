"use client";

import { useCallback, useEffect, useRef } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * 面板拖拽分隔条。
 * <p>
 * 支持鼠标拖拽与键盘左右箭头调整（步进 16px），拖拽时锁定全局光标与文本选择。
 *
 * @param side "left" | "right" 被调整的面板位于分隔条的哪一侧，决定拖拽方向的正负
 * @param width number 当前宽度
 * @param onResize (width: number) => void 宽度变化回调，越界由调用方夹取
 * @param label string 无障碍标签
 */
export function PanelResizer({
    side,
    width,
    onResize,
    label,
}: {
    side: "left" | "right";
    width: number;
    onResize: (width: number) => void;
    label: string;
}) {
    const draggingRef = useRef(false);
    const startXRef = useRef(0);
    const startWidthRef = useRef(0);

    const stop = useCallback(() => {
        draggingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    }, []);

    useEffect(() => {
        const move = (event: MouseEvent) => {
            if (!draggingRef.current) return;
            const delta = event.clientX - startXRef.current;
            onResize(startWidthRef.current + (side === "left" ? delta : -delta));
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", stop);
        return () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", stop);
        };
    }, [onResize, side, stop]);

    // 组件卸载时兜底恢复全局样式，避免拖拽中路由跳转后光标卡住。
    useEffect(() => stop, [stop]);

    return (
        <div
            role="separator"
            aria-orientation="vertical"
            aria-label={label}
            tabIndex={0}
            className={cn(
                "group relative w-px shrink-0 cursor-col-resize bg-[var(--hairline)]",
                "focus-visible:outline-none",
            )}
            onMouseDown={(event) => {
                draggingRef.current = true;
                startXRef.current = event.clientX;
                startWidthRef.current = width;
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
            }}
            onKeyDown={(event) => {
                if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                event.preventDefault();
                const delta = event.key === "ArrowLeft" ? -16 : 16;
                onResize(width + (side === "left" ? delta : -delta));
            }}
        >
            {/* 命中区域比视觉宽度大，避免 1px 难以抓取。 */}
            <span className="absolute inset-y-0 -left-1 -right-1 block" />
            <span className="absolute inset-y-0 left-0 w-px bg-[var(--s-action)] opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-100" />
        </div>
    );
}
