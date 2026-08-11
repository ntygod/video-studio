"""游标分页工具。

游标格式：base64url(JSON [created_at, id])。排序统一为
(created_at, id) 二元组，避免 offset 分页的漂移；新数据在前时用 desc。
"""

import base64
import json
from typing import Any


def encode_cursor(*parts) -> str:
    raw = json.dumps(list(parts), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> list | None:
    """返回原始游标列表（例如 [created_at, id] 或 [order_index, created_at, id]）。"""
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        parts = json.loads(raw.decode("utf-8"))
        if not isinstance(parts, list) or not parts:
            return None
        return parts
    except Exception:
        return None


def page(items: list[Any], limit: int, key: Any):
    """切页：limit+1 判断是否还有下一页。key 是最后一项的 (created_at, id)。"""
    page_items = items[:limit]
    next_cursor = encode_cursor(*key(page_items[-1])) if len(items) > limit and page_items else None
    return {"items": page_items, "next_cursor": next_cursor}
