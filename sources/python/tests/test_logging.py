import json
import logging
import threading
import time
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    InMemoryLogExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from tracing_skill_observability import logging as observability_logging
from tracing_skill_observability.logging import JsonLogFormatter, configure_logging


def test_json_formatter_includes_extra_fields():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.job_id = "job-1"

    payload = json.loads(JsonLogFormatter(service_name="svc").format(record))

    assert payload["message"] == "hello"
    assert payload["service_name"] == "svc"
    assert payload["job_id"] == "job-1"


def test_json_formatter_reserves_canonical_correlation_fields():
    record = logging.LogRecord(
        name="actual-logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="actual-message",
        args=(),
        exc_info=None,
    )
    record.trace_id = "f" * 32
    record.span_id = "f" * 16
    record.service_name = "spoofed-service"
    record.severity = "CRITICAL"
    record.timestamp = "spoofed-time"
    record.exception = "spoofed-exception"
    record.job_id = "job-1"

    with trace.use_span(NonRecordingSpan(_span_context(TraceFlags.SAMPLED))):
        payload = json.loads(JsonLogFormatter(service_name="actual-service").format(record))

    assert payload["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert payload["span_id"] == "0123456789abcdef"
    assert payload["service_name"] == "actual-service"
    assert payload["severity"] == "INFO"
    assert payload["timestamp"] != "spoofed-time"
    assert "exception" not in payload
    assert payload["job_id"] == "job-1"


def test_default_mode_is_stdout(monkeypatch):
    monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
    logger = logging.Logger("default-mode")

    configure_logging(root_logger=logger)

    assert len(logger.handlers) == 1
    assert type(logger.handlers[0]) is logging.StreamHandler


def test_otlp_body_is_identical_to_stdout_and_trace_flags_are_sampled(
    monkeypatch,
):
    exporter = InMemoryLogExporter()
    monkeypatch.setattr(
        observability_logging,
        "OTLPLogExporter",
        lambda **kwargs: exporter,
    )
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    logger = logging.Logger("otlp-mode")
    stdout = StringIO()
    trace_id = int("0123456789abcdef0123456789abcdef", 16)
    span_context = SpanContext(
        trace_id=trace_id,
        span_id=int("0123456789abcdef", 16),
        is_remote=False,
        trace_flags=TraceFlags.SAMPLED,
    )

    with redirect_stdout(stdout):
        configure_logging(
            service_name="host-worker",
            log_mode="otlp",
            root_logger=logger,
        )
        with trace.use_span(NonRecordingSpan(span_context)):
            logger.info("job.completed", extra={"job_id": "job-1"})

    exported = exporter.get_finished_logs()[0]
    assert exported.log_record.body == stdout.getvalue().rstrip("\n")
    assert exported.log_record.trace_flags == TraceFlags.SAMPLED
    assert exported.log_record.attributes["loki.format"] == "raw"
    resource = getattr(exported, "resource", None) or exported.log_record.resource
    assert resource.attributes["service.name"] == "host-worker"
    assert not any(key.startswith("k8s.") for key in resource.attributes)


def test_otlp_handler_owns_json_body_when_sdk_translation_ignores_formatter(
    monkeypatch,
):
    def translate_without_formatter(handler, record):
        return SimpleNamespace(body=record.getMessage(), attributes={})

    monkeypatch.setattr(
        observability_logging.LoggingHandler,
        "_translate",
        translate_without_formatter,
    )
    handler = observability_logging._JsonOtlpLoggingHandler(
        logger_provider=observability_logging.LoggerProvider()
    )
    handler.setFormatter(JsonLogFormatter(service_name="compatibility-test"))
    record = logging.LogRecord(
        name="compatibility-test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    translated = handler._translate(record)

    assert json.loads(translated.body)["message"] == "hello"
    assert translated.attributes["loki.format"] == "raw"


def test_otlp_only_does_not_write_stdout(monkeypatch):
    exporter = InMemoryLogExporter()
    monkeypatch.setattr(
        observability_logging,
        "OTLPLogExporter",
        lambda **kwargs: exporter,
    )
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    logger = logging.Logger("otlp-only-mode")
    stdout = StringIO()

    with redirect_stdout(stdout):
        configure_logging(log_mode="otlp-only", root_logger=logger)
        logger.info("host-only")

    assert stdout.getvalue() == ""
    exported = exporter.get_finished_logs()[0]
    assert exported.log_record.trace_flags == TraceFlags.DEFAULT


def test_otlp_log_preserves_unsampled_trace_flags(monkeypatch):
    exporter = InMemoryLogExporter()
    monkeypatch.setattr(
        observability_logging,
        "OTLPLogExporter",
        lambda **kwargs: exporter,
    )
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    logger = logging.Logger("unsampled-context")

    configure_logging(log_mode="otlp-only", root_logger=logger)
    with trace.use_span(NonRecordingSpan(_span_context(TraceFlags.DEFAULT))):
        logger.info("not-sampled")

    exported = exporter.get_finished_logs()[0]
    assert exported.log_record.trace_flags == TraceFlags.DEFAULT
    assert exported.log_record.trace_id == int(
        "0123456789abcdef0123456789abcdef", 16
    )


def test_otlp_attributes_drop_spoofed_canonical_fields(monkeypatch):
    exporter = InMemoryLogExporter()
    monkeypatch.setattr(
        observability_logging,
        "OTLPLogExporter",
        lambda **kwargs: exporter,
    )
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    logger = logging.Logger("canonical-otlp-attributes")

    configure_logging(
        service_name="actual-service",
        log_mode="otlp-only",
        root_logger=logger,
    )
    with trace.use_span(NonRecordingSpan(_span_context(TraceFlags.SAMPLED))):
        logger.info(
            "actual-message",
            extra={
                "trace_id": "f" * 32,
                "span_id": "f" * 16,
                "trace_flags": 0,
                "service_name": "spoofed-service",
                "severity": "CRITICAL",
                "timestamp": "spoofed-time",
                "exception": "spoofed-exception",
                "job_id": "job-1",
            },
        )

    record = exporter.get_finished_logs()[0].log_record
    assert not {
        "trace_id",
        "span_id",
        "trace_flags",
        "service_name",
        "severity",
        "timestamp",
        "exception",
    }.intersection(record.attributes)
    assert record.attributes["job_id"] == "job-1"
    assert record.trace_id == int("0123456789abcdef0123456789abcdef", 16)
    assert record.span_id == int("0123456789abcdef", 16)
    assert record.trace_flags == TraceFlags.SAMPLED


def test_standard_environment_selects_otlp_and_logs_endpoint(monkeypatch):
    exporter = InMemoryLogExporter()
    exporter_args = {}

    def make_exporter(**kwargs):
        exporter_args.update(kwargs)
        return exporter

    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp-only")
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "http://collector:4318/custom/logs",
    )
    monkeypatch.setattr(observability_logging, "OTLPLogExporter", make_exporter)
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    logger = logging.Logger("environment-mode")

    configure_logging(root_logger=logger)

    assert exporter_args["endpoint"] == "http://collector:4318/custom/logs"
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], observability_logging._JsonOtlpLoggingHandler)


def test_invalid_reconfiguration_preserves_working_logging_state(monkeypatch):
    logger = logging.Logger("transactional-reconfiguration")
    original_handler = logging.NullHandler()
    logger.addHandler(original_handler)
    logger.setLevel(logging.WARNING)
    provider = FakeLoggerProvider()
    monkeypatch.setattr(
        observability_logging,
        "_logger_providers",
        {id(logger): provider},
    )

    with pytest.raises(ValueError, match="log_mode"):
        configure_logging(log_mode="invalid", log_level="DEBUG", root_logger=logger)

    assert logger.handlers == [original_handler]
    assert logger.level == logging.WARNING
    assert observability_logging._logger_providers[id(logger)] is provider
    assert provider.shutdown_calls == 0


def test_reconfiguration_atomically_replaces_handlers_for_in_flight_records(
    monkeypatch,
):
    logger = logging.Logger("atomic-reconfiguration")
    started = threading.Event()
    release = threading.Event()
    first_old = RecordingHandler(started=started, release_event=release)
    second_old = RecordingHandler()
    replacement = RecordingHandler()
    logger.handlers = [first_old, second_old]
    monkeypatch.setattr(
        observability_logging.logging,
        "StreamHandler",
        lambda stream: replacement,
    )

    in_flight = threading.Thread(target=logger.info, args=("old-record",))
    in_flight.start()
    assert started.wait(timeout=1)
    configure_logging(log_mode="stdout", root_logger=logger)
    release.set()
    in_flight.join(timeout=1)
    logger.info("new-record")

    assert not in_flight.is_alive()
    assert first_old.messages == ["old-record"]
    assert second_old.messages == ["old-record"]
    assert replacement.messages == ["new-record"]


def test_direct_logging_construction_is_serialized(monkeypatch):
    logger = logging.Logger("serialized-construction")
    first_started = threading.Event()
    release = threading.Event()
    calls_lock = threading.Lock()
    active = 0
    max_active = 0
    calls = 0
    failures = []

    def make_exporter(**kwargs):
        nonlocal active, calls, max_active
        with calls_lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
            first_started.set()
        release.wait(timeout=1)
        with calls_lock:
            active -= 1
        return InMemoryLogExporter()

    def configure():
        try:
            configure_logging(log_mode="otlp-only", root_logger=logger)
        except Exception as exc:
            failures.append(exc)

    monkeypatch.setattr(observability_logging, "OTLPLogExporter", make_exporter)
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )
    first = threading.Thread(target=configure)
    second = threading.Thread(target=configure)
    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    time.sleep(0.05)

    assert calls == 1
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert failures == []
    assert not first.is_alive() and not second.is_alive()
    assert calls == 2
    assert max_active == 1


def test_failed_logging_candidate_is_shut_down(monkeypatch):
    logger = logging.Logger("failed-candidate")
    original_handler = logging.NullHandler()
    logger.handlers = [original_handler]
    candidate = FakeLoggerProvider()
    monkeypatch.setattr(
        observability_logging,
        "OTLPLogExporter",
        lambda **kwargs: FailingExporter(),
    )
    monkeypatch.setattr(
        observability_logging,
        "LoggerProvider",
        lambda **kwargs: candidate,
    )
    monkeypatch.setattr(
        observability_logging,
        "BatchLogRecordProcessor",
        lambda exporter: (_ for _ in ()).throw(RuntimeError("processor failed")),
    )

    with pytest.raises(RuntimeError, match="processor failed"):
        configure_logging(log_mode="otlp-only", root_logger=logger)

    assert logger.handlers == [original_handler]
    assert candidate.shutdown_calls == 1


def test_export_failure_is_reported_to_stderr_once(capsys):
    exporter = observability_logging._StderrReportingExporter(FailingExporter())

    assert exporter.export([]) is observability_logging._LogExportResult.FAILURE
    assert exporter.export([]) is observability_logging._LogExportResult.FAILURE

    assert capsys.readouterr().err.count("OTLP log export failed") == 1


def test_force_flush_logging_forwards_the_timeout(monkeypatch):
    provider = FakeLoggerProvider()
    monkeypatch.setattr(
        observability_logging,
        "_logger_providers",
        {1: provider},
    )

    assert observability_logging.force_flush_logging(timeout_millis=1234) is True
    assert provider.timeouts == [1234]


def test_force_flush_logging_deadline_includes_provider_lock_wait(monkeypatch):
    provider = FakeLoggerProvider()
    monkeypatch.setattr(observability_logging, "_logger_providers", {1: provider})
    locked = threading.Event()
    release = threading.Event()

    def hold_provider_lock():
        with observability_logging._logger_providers_lock:
            locked.set()
            release.wait(timeout=1)

    blocker = threading.Thread(target=hold_provider_lock)
    blocker.start()
    assert locked.wait(timeout=1)
    release_timer = threading.Timer(0.2, release.set)
    release_timer.start()

    started = time.monotonic()
    try:
        result = observability_logging.force_flush_logging(timeout_millis=10)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        release_timer.cancel()
        blocker.join(timeout=1)

    assert result is False
    assert elapsed < 0.1
    assert provider.timeouts == []
    assert not blocker.is_alive()


def test_real_batch_logging_flush_is_bounded_and_retains_lifecycle_lock(monkeypatch):
    exporter = BlockingRealLogExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    logger = logging.Logger("real-batch-deadline")
    LoggingHandler(logger_provider=provider).emit(
        logging.LogRecord(
            logger.name,
            logging.INFO,
            __file__,
            1,
            "queued",
            (),
            None,
        )
    )
    monkeypatch.setattr(
        observability_logging,
        "_logger_providers",
        {id(logger): provider},
    )
    release_timer = threading.Timer(0.2, exporter.release.set)
    release_timer.start()

    started = time.monotonic()
    try:
        first_result = observability_logging.force_flush_logging(timeout_millis=10)
        elapsed = time.monotonic() - started
        assert exporter.started.wait(timeout=1)
        second_started = time.monotonic()
        second_result = observability_logging.force_flush_logging(timeout_millis=10)
        second_elapsed = time.monotonic() - second_started
        reconfigure_thread = threading.Thread(
            target=lambda: configure_logging(log_mode="stdout", root_logger=logger)
        )
        reconfigure_thread.start()
        time.sleep(0.03)

        assert first_result is False
        assert second_result is False
        assert elapsed < 0.1
        assert second_elapsed < 0.1
        assert exporter.export_calls == 1
        assert reconfigure_thread.is_alive()
        assert exporter.shutdown_calls == 0
    finally:
        exporter.release.set()
        release_timer.cancel()
        reconfigure_thread.join(timeout=1)

    assert exporter.finished.wait(timeout=1)
    assert exporter.shutdown_calls == 1
    assert not reconfigure_thread.is_alive()


def test_selected_logger_provider_cannot_retire_during_flush(monkeypatch):
    provider = BlockingFlushLoggerProvider()
    logger = logging.Logger("flush-retirement")
    monkeypatch.setattr(
        observability_logging,
        "_logger_providers",
        {id(logger): provider},
    )
    flush_results = []
    flush_thread = threading.Thread(
        target=lambda: flush_results.append(
            observability_logging.force_flush_logging(timeout_millis=500)
        )
    )
    flush_thread.start()
    assert provider.flush_started.wait(timeout=1)

    reconfigure_thread = threading.Thread(
        target=lambda: configure_logging(log_mode="stdout", root_logger=logger)
    )
    reconfigure_thread.start()
    time.sleep(0.05)

    assert provider.shutdown_calls == 0
    provider.release_flush.set()
    flush_thread.join(timeout=1)
    reconfigure_thread.join(timeout=1)

    assert flush_results == [True]
    assert provider.shutdown_calls == 1
    assert not flush_thread.is_alive() and not reconfigure_thread.is_alive()


def test_retiring_logger_provider_cannot_be_selected_for_flush(monkeypatch):
    provider = BlockingShutdownLoggerProvider()
    logger = logging.Logger("retirement-selection")
    monkeypatch.setattr(
        observability_logging,
        "_logger_providers",
        {id(logger): provider},
    )
    reconfigure_thread = threading.Thread(
        target=lambda: configure_logging(log_mode="stdout", root_logger=logger)
    )
    reconfigure_thread.start()
    assert provider.shutdown_started.wait(timeout=1)

    started = time.monotonic()
    flush_result = observability_logging.force_flush_logging(timeout_millis=10)
    elapsed = time.monotonic() - started
    provider.release_shutdown.set()
    reconfigure_thread.join(timeout=1)

    assert flush_result is False
    assert elapsed < 0.1
    assert provider.timeouts == []
    assert not reconfigure_thread.is_alive()


class FailingExporter:
    def export(self, batch):
        raise RuntimeError("collector unavailable")

    def shutdown(self):
        pass


class BlockingRealLogExporter:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.export_calls = 0
        self.shutdown_calls = 0

    def export(self, batch):
        self.export_calls += 1
        self.started.set()
        self.release.wait(timeout=1)
        self.finished.set()
        return observability_logging._LogExportResult.SUCCESS

    def shutdown(self):
        self.shutdown_calls += 1


class FakeLoggerProvider:
    def __init__(self):
        self.timeouts = []
        self.shutdown_calls = 0

    def force_flush(self, *, timeout_millis):
        self.timeouts.append(timeout_millis)
        return True

    def add_log_record_processor(self, processor):
        pass

    def shutdown(self):
        self.shutdown_calls += 1


class BlockingFlushLoggerProvider(FakeLoggerProvider):
    def __init__(self):
        super().__init__()
        self.flush_started = threading.Event()
        self.release_flush = threading.Event()

    def force_flush(self, *, timeout_millis):
        self.timeouts.append(timeout_millis)
        self.flush_started.set()
        self.release_flush.wait(timeout=1)
        return True


class BlockingShutdownLoggerProvider(FakeLoggerProvider):
    def __init__(self):
        super().__init__()
        self.shutdown_started = threading.Event()
        self.release_shutdown = threading.Event()

    def shutdown(self):
        self.shutdown_calls += 1
        self.shutdown_started.set()
        self.release_shutdown.wait(timeout=1)


class RecordingHandler(logging.Handler):
    def __init__(self, *, started=None, release_event=None):
        super().__init__()
        self.started = started
        self.release_event = release_event
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())
        if self.started is not None:
            self.started.set()
        if self.release_event is not None:
            self.release_event.wait(timeout=1)


def _span_context(trace_flags: TraceFlags) -> SpanContext:
    return SpanContext(
        trace_id=int("0123456789abcdef0123456789abcdef", 16),
        span_id=int("0123456789abcdef", 16),
        is_remote=False,
        trace_flags=trace_flags,
    )
