"use client";

import { useEffect, useState } from "react";

/**
 * 订阅一个 CSS 媒体查询。
 * <p>
 * SSR 与首帧统一返回 false，挂载后再同步真实值，避免 hydration 不一致。
 *
 * @param query string 媒体查询串，例如 "(min-width: 1024px)"
 * @return boolean 是否匹配
 */
export function useMediaQuery(query: string): boolean {
    const [matches, setMatches] = useState(false);

    useEffect(() => {
        if (typeof window.matchMedia !== "function") return;
        const media = window.matchMedia(query);
        const sync = () => setMatches(media.matches);
        sync();
        media.addEventListener("change", sync);
        return () => media.removeEventListener("change", sync);
    }, [query]);

    return matches;
}

/**
 * 结构面板以固定栏形式展示的断点（T5.5：768–1280 平板两栏 = 结构 + 主区，助手走抽屉）。
 * <p>
 * 对应 Tailwind md；组件里不要再依赖 lg 判断结构栏可见性。
 */
export function useIsStructureInline(): boolean {
    return useMediaQuery("(min-width: 768px)");
}

/** 助手面板以固定栏形式展示的断点（Tailwind xl）。 */
export function useIsAgentInline(): boolean {
    return useMediaQuery("(min-width: 1280px)");
}
