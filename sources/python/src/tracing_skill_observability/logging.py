from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from ._resource import create_observability_resource, observability_service_name
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
_CANONICAL_FIELDS = {
    "exception",
    "logger",
    "message",
    "service_name",
    "severity",
    "span_id",
    "timestamp",
    "trace_flags",
    "trace_id",
}
_logger_providers: dict[int, LoggerProvider] = {}
_logger_providers_lock = Lock()


class JsonLogFormatter(logging.Formatter):
    def __init__(
        self,
        *,
        service_name: str | None = None,
        resource: Resource | None = None,
    ) -> None:
        super().__init__()
        resolved_resource = resource or create_observability_resource(service_name, None)
        self.service_name = observability_service_name(resolved_resource)

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
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
            if (
                key not in _RESERVED
                and key not in _CANONICAL_FIELDS
                and not key.startswith("_")
            ):
                body[key] = _json_safe(value)

        if record.exc_info:
            body["exception"] = self.formatException(record.exc_info)

        return json.dumps(body, separators=(",", ":"), sort_keys=True)


class _JsonOtlpLoggingHandler(LoggingHandler):
    def _translate(self, record: logging.LogRecord):
        translated = super()._translate(record)
        translated.body = self.format(record)
        for field in _CANONICAL_FIELDS:
            translated.attributes.pop(field, None)
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
    resource: Resource | None = None,
) -> LoggerProvider | None:
    logger = root_logger or logging.getLogger()
    with _logger_providers_lock:
        provider = None
        committed = False
        try:
            mode = _log_mode(log_mode)
            level = logging._checkLevel(log_level.upper())
            resolved_resource = (
                resource
                if resource is not None
                else _log_resource(service_name, service_version)
            )
            formatter = JsonLogFormatter(resource=resolved_resource)
            handlers: list[logging.Handler] = []
            if mode in {"stdout", "otlp"}:
                stdout_handler = logging.StreamHandler(sys.stdout)
                stdout_handler.setFormatter(formatter)
                handlers.append(stdout_handler)

            if mode in {"otlp", "otlp-only"}:
                exporter = _StderrReportingExporter(
                    OTLPLogExporter(endpoint=_log_endpoint(logs_endpoint, otlp_endpoint))
                )
                provider = LoggerProvider(resource=resolved_resource)
                provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
                otlp_handler = _JsonOtlpLoggingHandler(
                    level=level,
                    logger_provider=provider,
                )
                otlp_handler.setFormatter(formatter)
                handlers.append(otlp_handler)

            previous_provider = _logger_providers.get(id(logger))
            logger.handlers = handlers
            logger.setLevel(level)
            if provider is not None:
                _logger_providers[id(logger)] = provider
            else:
                _logger_providers.pop(id(logger), None)
            committed = True
        except Exception:
            if provider is not None and not committed:
                try:
                    provider.shutdown()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "observability.logging.candidate_shutdown_failed"
                    )
            raise

        if previous_provider is not None and previous_provider is not provider:
            try:
                previous_provider.shutdown()
            except Exception:
                logging.getLogger(__name__).exception(
                    "observability.logging.reconfigure_shutdown_failed"
                )
    return provider


def force_flush_logging(timeout_millis: int = 5_000) -> bool:
    """Flush configured OTLP log providers without raising."""

    deadline = time.monotonic() + max(0, timeout_millis) / 1_000
    if not _acquire_before(_logger_providers_lock, deadline):
        return False
    complete = Event()
    outcome = {"success": False}

    def flush_selected_providers() -> None:
        success = True
        try:
            for provider in _logger_providers.values():
                remaining = _remaining_millis(deadline)
                if remaining == 0:
                    success = False
                    continue
                try:
                    success = (
                        bool(provider.force_flush(timeout_millis=remaining)) and success
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "observability.logging.flush_failed"
                    )
                    success = False
            outcome["success"] = success
        finally:
            _logger_providers_lock.release()
            complete.set()

    try:
        Thread(
            target=flush_selected_providers,
            name="observability-logging-flush",
            daemon=True,
        ).start()
    except Exception:
        _logger_providers_lock.release()
        logging.getLogger(__name__).exception(
            "observability.logging.flush_worker_failed"
        )
        return False
    if not complete.wait(timeout=max(0.0, deadline - time.monotonic())):
        return False
    return bool(outcome["success"]) and time.monotonic() < deadline


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)


def _log_mode(log_mode: str | None) -> str:
    mode = (log_mode or os.getenv("OTEL_LOGS_EXPORTER") or "stdout").lower()
    if mode == "both":
        return "otlp"
    if mode == "none":
        return "stdout"
    if mode not in {"stdout", "otlp", "otlp-only"}:
        raise ValueError("log_mode must be one of: stdout, otlp, otlp-only, both")
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
    return create_observability_resource(service_name, service_version)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _remaining_millis(deadline: float) -> int:
    return max(0, math.ceil((deadline - time.monotonic()) * 1_000))


def _acquire_before(lock: Lock, deadline: float) -> bool:
    return lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
