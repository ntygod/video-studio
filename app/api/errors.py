import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.store.repositories import ConflictError, NotFoundError

logger = logging.getLogger("video-studio.api")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": f"resource not found: {exc.args[0]}"})

    @app.exception_handler(ConflictError)
    async def conflict(_request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        """兜底 handler：500 + {detail}，结构化记录，不再把栈回给前端。"""
        request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
        logger.error(
            json.dumps(
                {
                    "event": "unhandled_error",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": repr(exc),
                    "ts": time.time(),
                },
                ensure_ascii=False,
            ),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"内部错误（request_id={request_id}）"},
        )

