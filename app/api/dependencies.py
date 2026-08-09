from fastapi import Request

from app.store import UnitOfWork


def get_database(request: Request):
    return request.app.state.database


def get_media_store(request: Request):
    return request.app.state.media_store


def new_uow(request: Request) -> UnitOfWork:
    return UnitOfWork(request.app.state.database)

