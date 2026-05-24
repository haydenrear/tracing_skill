from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service_name: str | None = None) -> None:
        super().__init__()
        self.service_name = service_name or os.getenv("OTEL_SERVICE_NAME")

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self.service_name:
            body["service_name"] = self.service_name

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            body["trace_id"] = format(span_context.trace_id, "032x")
            body["span_id"] = format(span_context.span_id, "016x")

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                body[key] = _json_safe(value)

        if record.exc_info:
            body["exception"] = self.formatException(record.exc_info)

        return json.dumps(body, separators=(",", ":"), sort_keys=True)


def configure_logging(
    *,
    service_name: str | None = None,
    log_level: str = "INFO",
    root_logger: logging.Logger | None = None,
) -> None:
    logger = root_logger or logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service_name=service_name))
    logger.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)
