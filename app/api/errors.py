from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.store.repositories import ConflictError, NotFoundError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": f"resource not found: {exc.args[0]}"})

    @app.exception_handler(ConflictError)
    async def conflict(_request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

