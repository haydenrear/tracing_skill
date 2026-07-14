import json
import logging
from contextlib import redirect_stdout
from io import StringIO

from opentelemetry import trace
from opentelemetry.sdk._logs.export import (
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
    assert exported.resource.attributes["service.name"] == "host-worker"
    assert not any(
        key.startswith("k8s.") for key in exported.resource.attributes
    )


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
    assert exported.log_record.trace_flags == TraceFlags.SAMPLED


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
    assert isinstance(
        logger.handlers[0], observability_logging._JsonOtlpLoggingHandler
    )


def test_export_failure_is_reported_to_stderr_once(capsys):
    exporter = observability_logging._StderrReportingExporter(FailingExporter())

    assert exporter.export([]) is observability_logging._LogExportResult.FAILURE
    assert exporter.export([]) is observability_logging._LogExportResult.FAILURE

    assert capsys.readouterr().err.count("OTLP log export failed") == 1


class FailingExporter:
    def export(self, batch):
        raise RuntimeError("collector unavailable")

    def shutdown(self):
        pass
