from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.trace import TraceFlags

from .tracing import default_endpoint

try:
    from opentelemetry.sdk._logs.export import LogRecordExportResult as _LogExportResult
except ImportError:  # OpenTelemetry SDK 1.25 compatibility
    from opentelemetry.sdk._logs.export import LogExportResult as _LogExportResult

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


class _JsonOtlpLoggingHandler(LoggingHandler):
    def _translate(self, record: logging.LogRecord):
        translated = super()._translate(record)
        translated.trace_flags = translated.trace_flags or TraceFlags.SAMPLED
        translated.attributes["loki.format"] = "raw"
        return translated


class _StderrReportingExporter:
    def __init__(self, exporter: Any) -> None:
        self.exporter = exporter
        self._reported_failure = False

    def export(self, batch: Any) -> _LogExportResult:
        try:
            result = self.exporter.export(batch)
        except Exception as exc:
            self._report_failure(str(exc))
            return _LogExportResult.FAILURE
        if result is not _LogExportResult.SUCCESS:
            self._report_failure("exporter returned failure")
        return result

    def shutdown(self) -> None:
        self.exporter.shutdown()

    def _report_failure(self, detail: str) -> None:
        if self._reported_failure:
            return
        self._reported_failure = True
        print(f"OTLP log export failed: {detail}", file=sys.stderr)


def configure_logging(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    log_level: str = "INFO",
    log_mode: str | None = None,
    logs_endpoint: str | None = None,
    otlp_endpoint: str | None = None,
    root_logger: logging.Logger | None = None,
) -> None:
    logger = root_logger or logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(log_level.upper())

    mode = _log_mode(log_mode)
    formatter = JsonLogFormatter(service_name=service_name)
    if mode in {"stdout", "otlp"}:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        logger.addHandler(stdout_handler)

    if mode in {"otlp", "otlp-only"}:
        exporter = _StderrReportingExporter(
            OTLPLogExporter(endpoint=_log_endpoint(logs_endpoint, otlp_endpoint))
        )
        provider = LoggerProvider(
            resource=_log_resource(service_name, service_version)
        )
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        otlp_handler = _JsonOtlpLoggingHandler(
            level=logger.level,
            logger_provider=provider,
        )
        otlp_handler.setFormatter(formatter)
        logger.addHandler(otlp_handler)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)


def _log_mode(log_mode: str | None) -> str:
    mode = (log_mode or os.getenv("OTEL_LOGS_EXPORTER") or "stdout").lower()
    if mode == "both":
        return "otlp"
    if mode == "none":
        return "stdout"
    if mode not in {"stdout", "otlp", "otlp-only"}:
        raise ValueError(
            "log_mode must be one of: stdout, otlp, otlp-only, both"
        )
    return mode


def _log_endpoint(
    logs_endpoint: str | None,
    otlp_endpoint: str | None,
) -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if explicit:
        return explicit
    base = (
        logs_endpoint
        or otlp_endpoint
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or default_endpoint("logs")
    )
    return base if base.endswith("/v1/logs") else f"{base.rstrip('/')}/v1/logs"


def _log_resource(
    service_name: str | None,
    service_version: str | None,
) -> Resource:
    attributes = {
        SERVICE_NAME: service_name
        or os.getenv("OTEL_SERVICE_NAME")
        or "tracing-skill"
    }
    if service_version:
        attributes[SERVICE_VERSION] = service_version
    return Resource.create(attributes)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)
