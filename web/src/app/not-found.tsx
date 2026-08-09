import { Home } from "lucide-react";
import Link from "next/link";

/** 全局 404 页：居中卡片提示页面不存在并提供返回首页入口。 */
export default function NotFound() {
    return (
        <main
            className="flex h-dvh items-center justify-center overflow-y-auto px-6 py-10"
            style={{
                backgroundImage: "radial-gradient(var(--studio-line) 1px, transparent 1px)",
                backgroundSize: "16px 16px",
            }}
        >
            <section className="w-full max-w-md text-center">
                <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-lg border border-[var(--studio-line)] bg-[var(--studio-surface)] text-2xl font-semibold text-[var(--studio-ink)] shadow-[var(--studio-shadow)]">
                    404
                </div>
                <h1 className="text-[20px] font-semibold text-[var(--studio-ink)]">页面不存在</h1>
                <p className="mt-3 text-[13px] leading-6 text-[var(--studio-muted)]">
                    这个地址没有对应的页面，可能已经移动或被合并到其他入口。
                </p>
                <div className="mt-8 flex justify-center">
                    <Link
                        href="/"
                        className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--studio-action)] px-4 text-[13px] font-medium text-[var(--studio-action-foreground)] transition-colors hover:bg-[var(--studio-action-hover)]"
                    >
                        <Home className="size-4" />
                        返回首页
                    </Link>
                </div>
            </section>
        </main>
    );
}
