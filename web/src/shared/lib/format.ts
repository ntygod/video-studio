/** 通用格式化工具。 */

/**
 * 把后端的秒级时间戳格式化为相对时间。
 *
 * @param seconds number 秒级 Unix 时间戳
 * @return string 形如 "刚刚" / "12 分钟前" / "2026/8/9"
 */
export function relativeTime(seconds: number): string {
    const delta = Math.max(0, Date.now() / 1000 - seconds);
    if (delta < 60) return "刚刚";
    if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
    if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
    if (delta < 604800) return `${Math.floor(delta / 86400)} 天前`;
    return new Date(seconds * 1000).toLocaleDateString("zh-CN");
}

/**
 * 把秒级时间戳格式化为本地日期时间。
 *
 * @param seconds number | undefined 秒级 Unix 时间戳
 * @return string 本地化日期时间，无值时返回 "-"
 */
export function absoluteTime(seconds?: number): string {
    return seconds ? new Date(seconds * 1000).toLocaleString("zh-CN") : "-";
}

/**
 * 把 0~1 的进度转为 0~100 的整数百分比。
 *
 * @param value number 进度，超出区间会被夹取
 * @return number 0~100 的整数
 */
export function progressPercent(value: number): number {
    return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

/**
 * 秒数格式化为 mm:ss.s。
 *
 * @param seconds number 时长（秒）
 * @return string 形如 "01:48.0"
 */
export function duration(seconds: number): string {
    const safe = Math.max(0, seconds);
    const minutes = Math.floor(safe / 60);
    const rest = safe - minutes * 60;
    return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

/**
 * 字节数格式化为可读体积。
 *
 * @param bytes number 字节数
 * @return string 形如 "1.2 MB"
 */
export function fileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 把任意值格式化为带缩进的 JSON 文本。 */
export function jsonText(value: unknown): string {
    return JSON.stringify(value, null, 2);
}
