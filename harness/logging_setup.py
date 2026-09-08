"""Structured JSON logging.

Every device interaction emits one JSON object per line. Test runs can then be
diffed, grepped or fed to a log pipeline, which is the point: a test that fails
on the bench at 2am should leave behind something you can actually read.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

LOGGER_NAME = "harness"


class JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": record.getMessage(),
        }

        # Anything passed via extra={"context": {...}} rides along.
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(event: str, **context: Any) -> None:
    """Emit a structured event, e.g. log_event("write", char="threshold", n=2)."""
    get_logger().info(event, extra={"context": context})
