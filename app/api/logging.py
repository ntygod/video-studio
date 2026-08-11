"""结构化请求日志（T5.7）：JSON 行 + request_id 贯穿到 job 与 agent step。"""

import contextvars
import json
import logging
import time
import uuid

logger = logging.getLogger("video-studio.api")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def current_request_id() -> str:
    return request_id_var.get()


def install_request_logging(app) -> None:
    @app.middleware("http")
    async def log_request(request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(request_id)
        request.state.request_id = request_id
        start = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "ts": time.time(),
                    },
                    ensure_ascii=False,
                )
            )
