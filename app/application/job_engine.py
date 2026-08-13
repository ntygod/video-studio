"""Compatibility entry point for the durable Job engines."""

from app.application.jobs.engine import JobCanceled, JobEngine, get_job_engine
from app.application.jobs.runtime_executor_patch import (
    install_runtime_job_executor,
)

install_runtime_job_executor()

__all__ = ["JobEngine", "JobCanceled", "get_job_engine"]
