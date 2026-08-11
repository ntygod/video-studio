"""Job handler 共享上下文：数据库、设置、媒体存储、任务、协作式取消、事件写入。"""

from dataclasses import dataclass
from typing import Any, Callable

from app.store import UnitOfWork


@dataclass
class JobContext:
    database: Any
    settings: Any
    media_store: Any
    job: dict[str, Any]
    should_cancel: Callable[[], bool]

    def emit(
        self,
        message: str,
        level: str = "info",
        stage: str = "",
        progress: float | None = None,
    ) -> None:
        with UnitOfWork(self.database) as uow:
            uow.jobs.add_event(
                self.job["id"], message, level=level, stage=stage, progress=progress
            )

    def set_progress(self, progress: float) -> None:
        with UnitOfWork(self.database) as uow:
            uow.jobs.update_state(self.job["id"], "running", progress=progress)
