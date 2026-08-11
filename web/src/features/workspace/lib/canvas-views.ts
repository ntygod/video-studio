/**
 * 画布视图的纯常量与工具（无 "use client"）。
 * <p>
 * 服务端页面（如 /projects/[id] 重定向）也需要读取默认视图，
 * 因此不能放在 "use client" 的 store 里——Next 会把客户端模块的值
 * 变成"只能在客户端调用"的代理，服务端一用就抛错。
 */

export type CanvasView = "story" | "media" | "produce" | "brief" | "board";

/** 合法视图集合，用于校验来自 URL 的值。 */
export const CANVAS_VIEWS: readonly CanvasView[] = ["story", "media", "produce", "brief", "board"] as const;

/** 默认视图。 */
export const DEFAULT_CANVAS_VIEW: CanvasView = "story";

/**
 * 把任意字符串收敛为合法视图。
 *
 * @param value string | undefined | null 来自路由的原始值
 * @return CanvasView 合法视图，非法时回落到默认视图
 */
export function normalizeCanvasView(value: string | undefined | null): CanvasView {
    return CANVAS_VIEWS.includes(value as CanvasView) ? (value as CanvasView) : DEFAULT_CANVAS_VIEW;
}
