import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge 默认把未知的 `text-*` 当作颜色类，会与 `text-[颜色变量]`
 * 冲突并丢掉我们自定义的字号工具（text-title / text-caption / text-mono-sm 等）。
 * 这里把 docs/ui-craft.md §2.2 的七档字号显式声明为字号组，避免误删。
 */
const twMerge = extendTailwindMerge({
    extend: {
        theme: {
            // tailwind-merge v3 的字号主题键是 `text`（对应 Tailwind v4 的 --text-*）。
            text: ["display", "title", "heading", "body", "label", "caption", "mono-sm"],
        },
    },
});

/**
 * 合并多个 className 输入，解决 Tailwind 工具类冲突。
 * <p>
 * 先用 clsx 把任意形态的输入归一为字符串，再交给 tailwind-merge 去掉相互冲突的类（后者覆盖前者）。
 *
 * @param inputs 类名，可为字符串、数组、对象或假值
 * @return 去重冲突后的单个 className 字符串
 */
export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}
