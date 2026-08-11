/**
 * 单例 SSE 客户端：指数退避重连、Last-Event-ID 续传、done 后自动关闭。
 * <p>
 * EventSource 无法自定义请求头，因此 Last-Event-ID 通过 query 参数传给后端，
 * 后端按 last_event_id 从 agent_steps 补发历史事件。
 */

const API_BASE = (process.env.NEXT_PUBLIC_SERVER_URL || "").replace(/\/+$/, "");

export type StreamEvent = {
    id?: string;
    type: string;
    [key: string]: unknown;
};

export type StreamHandlers = {
    onEvent: (event: StreamEvent) => void;
    /** SSE 不可用（后端未就绪/代理不支持）时切换到轮询降级。 */
    onFallback: () => void;
};

/** 订阅一个 Agent 回合的事件流，返回取消函数。 */
export function subscribeTurnStream(
    conversationId: string,
    turnId: string,
    handlers: StreamHandlers,
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
            let event: StreamEvent;
            try {
                event = JSON.parse(message.data) as StreamEvent;
            } catch {
                return;
            }
            if (event.id) lastEventId = String(event.id);
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
