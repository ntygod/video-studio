/**
 * 单例 SSE 客户端：指数退避重连、Last-Event-ID 续传、done 后自动关闭。
 * <p>
 * EventSource 无法自定义请求头，因此 Last-Event-ID 通过 query 参数传给后端，
 * 后端按 last_event_id 从持久化 RuntimeTaskEvent 补发结构化事件。
 */

const API_BASE = (process.env.NEXT_PUBLIC_SERVER_URL || "").replace(/\/+$/, "");

export type StreamEvent = {
    id?: string;
    type: string;
    durable?: boolean;
    [key: string]: unknown;
};

export type StreamHandlers<TEvent extends StreamEvent = StreamEvent> = {
    onEvent: (event: TEvent) => void;
    /** SSE 不可用（后端未就绪/代理不支持）时切换到轮询降级。 */
    onFallback: () => void;
};

/**
 * 只有持久化事件才能成为重连游标。实时 token 即使带有本地展示 ID，
 * 也不能覆盖 RuntimeTaskEvent 的单调序号，否则重连会退回整段重放。
 */
export function durableStreamCursor(event: StreamEvent): string | null {
    if (!event.id || event.durable === false) return null;
    return String(event.id);
}

/** 订阅一个 Agent 回合的事件流，返回取消函数。 */
export function subscribeTurnStream<
    TEvent extends StreamEvent = StreamEvent,
>(
    conversationId: string,
    turnId: string,
    handlers: StreamHandlers<TEvent>,
): () => void {
    let closed = false;
    let source: EventSource | null = null;
    let retries = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEventId = "";
    let receivedAny = false;
    let fallbackNotified = false;

    const url =
        API_BASE +
        `/api/conversations/${encodeURIComponent(conversationId)}/stream?turn_id=${encodeURIComponent(turnId)}`;

    const open = () => {
        if (closed) return;
        const withCursor = lastEventId ? `&last_event_id=${encodeURIComponent(lastEventId)}` : "";
        source = new EventSource(url + withCursor);

        source.onopen = () => {
            retries = 0;
        };

        source.onmessage = (message) => {
            if (closed) return;
            receivedAny = true;
            let event: TEvent;
            try {
                event = JSON.parse(message.data) as TEvent;
            } catch {
                return;
            }
            const cursor = durableStreamCursor(event);
            if (cursor) lastEventId = cursor;
            handlers.onEvent(event);
            if (event.type === "done") close();
        };

        source.onerror = () => {
            if (closed) return;
            if (!receivedAny && !fallbackNotified) {
                fallbackNotified = true;
                handlers.onFallback();
            }
            source?.close();
            if (closed) return;
            retries += 1;
            const delay = Math.min(1000 * 2 ** Math.min(retries, 5), 15000);
            reconnectTimer = setTimeout(open, delay);
        };
    };

    const close = () => {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        source?.close();
    };

    open();
    return close;
}
