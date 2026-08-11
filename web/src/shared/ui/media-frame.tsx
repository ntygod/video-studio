"use client";

import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * 媒体统一入口：坐在 --s-canvas 上，不描边，圆角 xs。
 * 透明图垫棋盘格；媒体出血到容器边缘。
 */
export function MediaFrame({
    ratio = "16 / 9",
    fit = "cover",
    checkerboard = false,
    src,
    alt,
    children,
    className,
}: {
    ratio?: string;
    fit?: "cover" | "contain";
    checkerboard?: boolean;
    src?: string;
    alt?: string;
    children?: ReactNode;
    className?: string;
}) {
    const checkerStyle: CSSProperties | undefined = checkerboard
        ? {
              backgroundImage:
                  "repeating-conic-gradient(var(--s-faint) 0% 25%, transparent 0% 50%)",
              backgroundSize: "12px 12px",
              opacity: 0.25,
          }
        : undefined;

    return (
        <div
            className={cn(
                "relative w-full overflow-hidden rounded-[var(--r-xs)] bg-[var(--s-canvas)]",
                className,
            )}
            style={{ aspectRatio: ratio }}
        >
            {/* 棋盘格必须垫在图片下面。盖在上面会给画面蒙一层灰网格。 */}
            {checkerboard ? <div aria-hidden className="absolute inset-0" style={checkerStyle} /> : null}
            {src ? (
                <img
                    src={src}
                    alt={alt ?? ""}
                    loading="lazy"
                    className={cn(
                        "relative h-full w-full",
                        fit === "cover" ? "object-cover" : "object-contain",
                    )}
                />
            ) : null}
            {/* children 与 src 可以并存：src 出图，children 放角标 / 进度 / 悬停操作条。 */}
            {children}
        </div>
    );
}
