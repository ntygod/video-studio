import { Home } from "lucide-react";

import { Button, Surface, Text } from "@/shared/ui";

/** 全局 404 页：居中卡片提示页面不存在并提供返回首页入口。 */
export default function NotFound() {
    return (
        <main
            className="flex h-dvh items-center justify-center overflow-y-auto px-6 py-10"
            style={{
                backgroundImage: "radial-gradient(var(--hairline) 1px, transparent 1px)",
                backgroundSize: "16px 16px",
            }}
        >
            <Surface level="panel" radius="md" lift inset="6" className="w-full max-w-md text-center">
                <Surface level="raised" radius="md" className="mx-auto mb-6 flex size-16 items-center justify-center">
                    <Text variant="title" tone="ink" weight={600}>
                        404
                    </Text>
                </Surface>
                <Text as="h1" variant="title" tone="ink">
                    页面不存在
                </Text>
                <Text as="p" variant="body" tone="muted" className="mt-3 leading-6">
                    这个地址没有对应的页面，可能已经移动或被合并到其他入口。
                </Text>
                <div className="mt-8 flex justify-center">
                    <Button variant="primary" href="/" icon={<Home className="size-4" />}>
                        返回首页
                    </Button>
                </div>
            </Surface>
        </main>
    );
}
