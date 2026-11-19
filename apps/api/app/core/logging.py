"""Structured logging configuration.

Logs are emitted as JSON in production and as readable key/value lines in development.
Secrets, tokens and document contents are never passed to the logger by application code.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config.settings import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if settings.LOG_JSON:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Keep third-party loggers quieter than our own.
    for noisy in ("httpx", "httpcore", "boto3", "botocore", "s3transfer", "PIL"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
    _CONFIGURED = True


def get_logger(name: str = "resolve") -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)
