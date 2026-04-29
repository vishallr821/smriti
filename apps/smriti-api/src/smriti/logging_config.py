"""Structured logging configuration for Smriti API."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")


def configure_logging() -> None:
    """Configure structlog with JSON output and request_id context."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
