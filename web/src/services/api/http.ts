"use client";

/** 后端基地址，去掉尾部斜杠以便直接拼接路径。 */
const API_BASE = (process.env.NEXT_PUBLIC_SERVER_URL || "").replace(/\/+$/, "");

/** 是否输出请求日志，由 NEXT_PUBLIC_API_DEBUG 控制。 */
const DEBUG = process.env.NEXT_PUBLIC_API_DEBUG === "1";

/**
 * 后端返回的结构化错误。
 * <p>
 * 保留 status 与 detail，便于调用方按状态码分支处理（例如 409 版本冲突需要重新拉取后重试）。
 */
export class ApiError extends Error {
    readonly status: number;
    readonly detail: unknown;

    constructor(status: number, message: string, detail?: unknown) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
    }

    /** 乐观锁冲突：调用方应重新拉取最新 revision 后重试。 */
    get isConflict(): boolean {
        return this.status === 409;
    }

    /** 资源不存在：调用方通常应清理本地缓存中的该条目。 */
    get isNotFound(): boolean {
        return this.status === 404;
    }
}

/**
 * 把 query 参数对象序列化为查询串，自动跳过 undefined / null / 空字符串。
 *
 * @param params Record<string, unknown> | undefined 查询参数
 * @return string 形如 "?a=1&b=2" 的查询串，无参数时返回空串
 */
export function toQuery(params?: Record<string, unknown>): string {
    if (!params) return "";
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null || value === "") return;
        search.append(key, String(value));
    });
    const query = search.toString();
    return query ? "?" + query : "";
}

async function readErrorDetail(response: Response): Promise<{ message: string; detail: unknown }> {
    const fallback = `请求失败（${response.status}）`;
    try {
        const body = await response.json();
        const detail = (body as { detail?: unknown })?.detail;
        if (typeof detail === "string") return { message: detail, detail };
        if (detail !== undefined) return { message: fallback, detail };
        return { message: fallback, detail: body };
    } catch {
        return { message: fallback, detail: undefined };
    }
}

/**
 * 统一的后端请求入口。
 *
 * @param path string 以 / 开头的接口路径
 * @param init RequestInit | undefined fetch 配置，body 为 FormData 时不注入 JSON 头
 * @return Promise<T> 解析后的响应体，204 返回 undefined
 * @throws ApiError 非 2xx 响应
 */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const isForm = init?.body instanceof FormData;
    const url = API_BASE + path;

    if (DEBUG) console.log(`[API →] ${init?.method || "GET"} ${path}`);

    const response = await fetch(url, {
        ...init,
        cache: "no-store",
        headers: isForm ? init?.headers : { "Content-Type": "application/json", ...(init?.headers || {}) },
    });

    if (!response.ok) {
        const { message, detail } = await readErrorDetail(response);
        if (DEBUG) console.warn(`[API ✕] ${response.status} ${path} — ${message}`);
        throw new ApiError(response.status, message, detail);
    }

    if (response.status === 204) return undefined as T;

    const data = (await response.json()) as T;
    if (DEBUG) console.log(`[API ←] ${path}`, data);
    return data;
}

/** GET 请求。 */
export function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
    return api<T>(path + toQuery(params));
}

/** POST 请求，body 自动 JSON 序列化。 */
export function post<T>(path: string, body?: unknown): Promise<T> {
    return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

/** PATCH 请求，body 自动 JSON 序列化。 */
export function patch<T>(path: string, body: unknown): Promise<T> {
    return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

/** DELETE 请求。 */
export function del<T>(path: string): Promise<T> {
    return api<T>(path, { method: "DELETE" });
}

/** 表单 POST，用于文件上传。 */
export function postForm<T>(path: string, body: FormData): Promise<T> {
    return api<T>(path, { method: "POST", body, headers: {} });
}

/** 路径片段转义，避免 id 中出现特殊字符时拼错 URL。 */
export function seg(value: string): string {
    return encodeURIComponent(value);
}

/** 后端媒体路由的挂载点，见 app/api/routes/media.py。 */
const MEDIA_PREFIX = "/media/";

/** 素材在磁盘上的根目录片段，用于从绝对路径里截出可访问的相对地址。 */
const MEDIA_ROOT_MARKER = "/data/media/";

/**
 * 把素材 uri 转成浏览器可直接访问的地址。
 * <p>
 * 后端 MediaStore.write_bytes 返回的是**绝对文件系统路径**（例如
 * `D:/WorkSpace/.../data/media/<project>/<file>.png`），并被原样写进 asset.uri。
 * 浏览器无法加载这种地址，所以这里截出 data/media 之后的部分，映射到 /media 路由。
 * 后端把 uri 改成相对路径后，这里的兼容分支可以删掉。
 *
 * @param uri string 素材 uri，可能是绝对路径、相对路径或完整 URL
 * @return string 可用于 img/video/audio src 的地址
 */
export function mediaUrl(uri: string): string {
    if (!uri) return "";
    if (/^(https?:|data:|blob:)/i.test(uri)) return uri;

    const normalized = uri.replace(/\\/g, "/");
    if (normalized.startsWith(MEDIA_PREFIX)) return API_BASE + normalized;

    const markerAt = normalized.indexOf(MEDIA_ROOT_MARKER);
    const relative =
        markerAt >= 0 ? normalized.slice(markerAt + MEDIA_ROOT_MARKER.length) : normalized.replace(/^\/+/, "");

    return API_BASE + MEDIA_PREFIX + relative;
}
