import asyncio
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from tracing_skill_observability import (
    TraceHandle,
    current_trace_handle,
    current_trace_id,
    extract_trace_context,
    inject_trace_context,
    traced_span,
)
from tracing_skill_observability import metrics as observability_metrics, tracing

OTLP_ENV_VARS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)


@pytest.fixture(autouse=True)
def clear_otlp_env(monkeypatch: pytest.MonkeyPatch):
    """Endpoint resolution reads the environment, so no test may inherit one."""

    for name in OTLP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tracing, "_warned_default_endpoint", False)


def test_default_endpoint_is_reachable_from_the_docker_host():
    """The default must resolve somewhere. An in-cluster .svc name does not.

    The monitoring gateway publishes its ports on the Docker host, so localhost
    is correct for the bare-host case -- the one case with no chart to inject
    OTEL_EXPORTER_OTLP_ENDPOINT, and therefore the one that needs a default.
    """

    assert tracing.DEFAULT_OTLP_ENDPOINT == "http://localhost:4318"
    assert ".svc" not in tracing.DEFAULT_OTLP_ENDPOINT


def test_default_endpoint_warns_once_when_nothing_configured(
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.WARNING, logger="tracing_skill_observability.tracing"):
        first = tracing.default_endpoint("traces")
        second = tracing.default_endpoint("traces")

    assert first == second == tracing.DEFAULT_OTLP_ENDPOINT
    assert [record.message for record in caplog.records] == [
        "observability.endpoint.defaulted"
    ]


def test_trace_endpoint_falls_back_to_the_default():
    assert tracing._trace_endpoint(None) == "http://localhost:4318/v1/traces"


def test_trace_endpoint_prefers_explicit_argument_over_default():
    assert (
        tracing._trace_endpoint("http://host.k3d.internal:4318")
        == "http://host.k3d.internal:4318/v1/traces"
    )


def test_trace_endpoint_prefers_explicit_argument_over_base_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://base:4318")

    assert tracing._trace_endpoint("http://arg:4318") == "http://arg:4318/v1/traces"


def test_trace_endpoint_uses_base_env_when_no_argument(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://host.k3d.internal:4318")

    assert tracing._trace_endpoint(None) == "http://host.k3d.internal:4318/v1/traces"


def test_signal_env_var_overrides_argument_and_base_env(
    monkeypatch: pytest.MonkeyPatch,
):
    """The signal-specific variable wins outright, matching logs and metrics.

    It is the last word deliberately: it is how an operator redirects one signal
    of an already-configured process without editing it.
    """

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://base:4318")
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://signal:4318/v1/traces"
    )

    assert tracing._trace_endpoint("http://arg:4318") == "http://signal:4318/v1/traces"


def test_trace_endpoint_does_not_double_append_the_signal_path():
    assert (
        tracing._trace_endpoint("http://localhost:4318/v1/traces")
        == "http://localhost:4318/v1/traces"
    )


def test_trace_endpoint_tolerates_a_trailing_slash():
    assert (
        tracing._trace_endpoint("http://localhost:4318/")
        == "http://localhost:4318/v1/traces"
    )


def test_current_trace_handle_exposes_lowercase_32_hex_id():
    span_context = _span_context()

    with trace.use_span(NonRecordingSpan(span_context)):
        handle = current_trace_handle()

        assert handle is not None
        assert handle.trace_id == "0123456789abcdef0123456789abcdef"
        assert str(handle) == handle.trace_id
        assert current_trace_id() == handle.trace_id


@pytest.mark.parametrize(
    "trace_id",
    [
        "0" * 32,
        "0123456789ABCDEF0123456789ABCDEF",
        "0123456789abcdef",
        "g123456789abcdef0123456789abcdef",
    ],
)
def test_trace_handle_rejects_invalid_agent_ids(trace_id):
    with pytest.raises(ValueError, match="lowercase 32-hex"):
        TraceHandle(trace_id)


def test_w3c_context_round_trip_preserves_incoming_trace():
    with trace.use_span(NonRecordingSpan(_span_context())):
        carrier = inject_trace_context()

    extracted = extract_trace_context(carrier)
    remote_context = trace.get_current_span(extracted).get_span_context()

    assert carrier["traceparent"].startswith(
        "00-0123456789abcdef0123456789abcdef-0123456789abcdef-"
    )
    assert remote_context.is_valid
    assert remote_context.is_remote
    assert format(remote_context.trace_id, "032x") == (
        "0123456789abcdef0123456789abcdef"
    )


def test_w3c_context_extraction_treats_http_header_names_case_insensitively():
    extracted = extract_trace_context(
        {
            "TraceParent": (
                "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
            ),
            "TraceState": "vendor=value",
        }
    )

    remote_context = trace.get_current_span(extracted).get_span_context()

    assert remote_context.is_valid
    assert remote_context.is_remote
    assert remote_context.trace_flags == TraceFlags.SAMPLED
    assert format(remote_context.trace_id, "032x") == (
        "0123456789abcdef0123456789abcdef"
    )


@pytest.mark.parametrize(
    "carrier",
    [None, {}, {"traceparent": "not-a-traceparent"}],
)
def test_absent_or_malformed_w3c_context_fails_open(carrier):
    extracted = extract_trace_context(carrier)

    assert not trace.get_current_span(extracted).get_span_context().is_valid


def test_w3c_injection_failure_returns_the_original_carrier(caplog):
    carrier = RejectingCarrier()

    with trace.use_span(NonRecordingSpan(_span_context())):
        returned = inject_trace_context(carrier)

    assert returned is carrier
    assert "observability.trace_context.inject_failed" in caplog.text


def test_force_flush_tracing_forwards_the_timeout(monkeypatch):
    provider = FakeTracerProvider()
    monkeypatch.setattr(tracing, "_tracer_provider", provider)

    assert tracing.force_flush_tracing(timeout_millis=1234) is True
    assert provider.timeouts == [1234]


def test_real_batch_tracing_flush_is_bounded_and_deduplicated(monkeypatch):
    exporter = BlockingSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    with provider.get_tracer("real-batch-deadline").start_as_current_span("queued"):
        pass
    monkeypatch.setattr(tracing, "_tracer_provider", provider)
    release_timer = threading.Timer(0.2, exporter.release.set)
    release_timer.start()

    started = time.monotonic()
    try:
        first_result = tracing.force_flush_tracing(timeout_millis=10)
        elapsed = time.monotonic() - started
        assert exporter.started.wait(timeout=1)
        second_result = tracing.force_flush_tracing(timeout_millis=10)

        assert first_result is False
        assert second_result is False
        assert elapsed < 0.1
        assert exporter.export_calls == 1
    finally:
        exporter.release.set()
        release_timer.cancel()

    assert exporter.finished.wait(timeout=1)
    provider.shutdown()


def test_configure_tracing_reuses_the_preinstalled_sdk_provider():
    script = textwrap.dedent(
        """
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from tracing_skill_observability import configure_tracing, force_flush_tracing, get_tracer

        class HostProvider(TracerProvider):
            def __init__(self):
                super().__init__()
                self.flush_timeouts = []

            def force_flush(self, timeout_millis=30000):
                self.flush_timeouts.append(timeout_millis)
                return super().force_flush(timeout_millis=timeout_millis)

        exporter = InMemorySpanExporter()
        provider = HostProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        configured = configure_tracing(
            service_name="library-must-not-own-this-provider",
            otlp_endpoint="http://127.0.0.1:9",
        )
        with get_tracer("host-provider-test").start_as_current_span("host-span"):
            pass

        assert configured is provider
        assert trace.get_tracer_provider() is provider
        assert force_flush_tracing(timeout_millis=123)
        assert provider.flush_timeouts == [123]
        assert [span.name for span in exporter.get_finished_spans()] == ["host-span"]
        provider.shutdown()
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_aggregate_uses_host_provider_resource_for_every_signal():
    script = textwrap.dedent(
        """
        import json
        import logging
        from opentelemetry import trace
        from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        import tracing_skill_observability as observability
        from tracing_skill_observability import logging as observability_logging

        host_resource = Resource.create({"service.name": "host-service"})
        host_provider = TracerProvider(resource=host_resource)
        trace.set_tracer_provider(host_provider)
        log_exporter = InMemoryLogExporter()
        observability_logging.OTLPLogExporter = lambda **kwargs: log_exporter
        observability_logging.BatchLogRecordProcessor = SimpleLogRecordProcessor
        captured = {}
        observability.configure_metrics = (
            lambda **kwargs: captured.setdefault("metrics_resource", kwargs["resource"])
        )

        observability.configure_observability(
            service_name="requested-service",
            log_mode="otlp",
            otlp_endpoint="http://127.0.0.1:9",
        )
        logging.getLogger().info("identity.probe")
        exported = log_exporter.get_finished_logs()[0]
        log_resource = getattr(exported, "resource", None) or exported.log_record.resource
        body = json.loads(exported.log_record.body)
        identities = {
            host_provider.resource.attributes["service.name"],
            log_resource.attributes["service.name"],
            captured["metrics_resource"].attributes["service.name"],
            body["service_name"],
        }
        assert identities == {"host-service"}, identities

        observability_logging._logger_providers[id(logging.getLogger())].shutdown()
        host_provider.shutdown()
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_traces_logs_and_metrics_resolve_the_same_resource_identity():
    script = textwrap.dedent(
        """
        import json
        from tracing_skill_observability import configure_tracing
        from tracing_skill_observability.logging import JsonLogFormatter, _log_resource
        from tracing_skill_observability.metrics import _metrics_resource
        import logging

        trace_resource = configure_tracing(
            service_version="1.2.3",
            otlp_endpoint="http://127.0.0.1:9",
        ).resource
        resources = [
            trace_resource.attributes,
            _log_resource(None, "1.2.3").attributes,
            _metrics_resource(None, "1.2.3").attributes,
        ]
        assert resources[0] == resources[1] == resources[2], resources
        record = logging.LogRecord(
            "resource-test", logging.INFO, "<probe>", 1, "hello", (), None
        )
        body = json.loads(JsonLogFormatter().format(record))
        assert body["service_name"] == "resource-only", body
        """
    )
    env = os.environ.copy()
    env.pop("OTEL_SERVICE_NAME", None)
    env["OTEL_RESOURCE_ATTRIBUTES"] = (
        "service.name=resource-only,service.namespace=payments,custom.key=value"
    )
    env["DEPLOYMENT_ENVIRONMENT"] = "certification"

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_traced_span_decorator_wraps_sync_function():
    @traced_span("unit.sync", kind="test")
    def add_one(value: int) -> int:
        return value + 1

    assert add_one(1) == 2


def test_traced_span_decorator_wraps_sync_function_without_args():
    @traced_span
    def add_one(value: int) -> int:
        return value + 1

    assert add_one(1) == 2


def test_traced_span_decorator_wraps_async_function():
    @traced_span("unit.async")
    async def add_one(value: int) -> int:
        return value + 1

    assert asyncio.run(add_one(1)) == 2


@pytest.mark.parametrize("recorder_raises", [False, True])
def test_shared_bounded_span_helpers_record_trace_correlation(
    monkeypatch,
    recorder_raises,
):
    calls = []

    def record_correlation():
        calls.append("correlation")
        if recorder_raises:
            raise ValueError("recorder failure")
        return False

    monkeypatch.setattr(
        observability_metrics,
        "record_trace_correlation",
        record_correlation,
    )

    with tracing.span("unit.context"):
        context_result = "context-result"

    @traced_span("unit.sync.correlation")
    def sync_operation():
        return "sync-result"

    @traced_span("unit.async.correlation")
    async def async_operation():
        return "async-result"

    assert context_result == "context-result"
    assert sync_operation() == "sync-result"
    assert asyncio.run(async_operation()) == "async-result"

    assert calls == ["correlation", "correlation", "correlation"]


@pytest.mark.parametrize("helper", ["context", "sync", "async"])
def test_correlation_recorder_exception_does_not_mask_business_exception(
    monkeypatch,
    helper,
):
    original = RuntimeError(f"{helper} business failure")

    def fail_correlation():
        raise ValueError("recorder failure")

    monkeypatch.setattr(
        observability_metrics,
        "record_trace_correlation",
        fail_correlation,
    )

    with pytest.raises(RuntimeError) as captured:
        if helper == "context":
            with tracing.span("unit.context.failure"):
                raise original
        elif helper == "sync":

            @traced_span("unit.sync.failure")
            def fail():
                raise original

            fail()
        else:

            @traced_span("unit.async.failure")
            async def fail():
                raise original

            asyncio.run(fail())

    assert captured.value is original


def test_traced_span_records_sync_exception(monkeypatch: pytest.MonkeyPatch):
    fake_span = FakeSpan()
    monkeypatch.setattr(tracing, "get_tracer", lambda name=None: FakeTracer(fake_span))

    @traced_span("unit.fail")
    def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        fail()

    assert fake_span.exceptions
    assert fake_span.status is not None
    assert fake_span.status.status_code.name == "ERROR"


def test_traced_span_records_async_exception(monkeypatch: pytest.MonkeyPatch):
    fake_span = FakeSpan()
    monkeypatch.setattr(tracing, "get_tracer", lambda name=None: FakeTracer(fake_span))

    @traced_span("unit.async.fail")
    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(fail())

    assert fake_span.exceptions
    assert fake_span.status is not None
    assert fake_span.status.status_code.name == "ERROR"


def test_traced_span_records_exactly_one_exception_event():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    @traced_span("unit.single-exception")
    def fail():
        raise RuntimeError("boom")

    original_get_tracer = tracing.get_tracer
    tracing.get_tracer = lambda name=None: provider.get_tracer(name or "test")
    try:
        with pytest.raises(RuntimeError, match="boom"):
            fail()
    finally:
        tracing.get_tracer = original_get_tracer
        provider.shutdown()

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert [event.name for event in finished[0].events] == ["exception"]
    assert finished[0].status.status_code.name == "ERROR"


class FakeSpan:
    def __init__(self):
        self.attributes = {}
        self.exceptions = []
        self.status = None

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def set_status(self, status):
        self.status = status


class FakeTracer:
    def __init__(self, span):
        self.span = span

    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield self.span


class FakeTracerProvider:
    def __init__(self):
        self.timeouts = []

    def force_flush(self, *, timeout_millis):
        self.timeouts.append(timeout_millis)
        return True


class BlockingSpanExporter:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.export_calls = 0

    def export(self, spans):
        self.export_calls += 1
        self.started.set()
        self.release.wait(timeout=1)
        self.finished.set()
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


class RejectingCarrier(dict):
    def __setitem__(self, key, value):
        raise RuntimeError("carrier is read-only")


def _span_context() -> SpanContext:
    return SpanContext(
        trace_id=int("0123456789abcdef0123456789abcdef", 16),
        span_id=int("0123456789abcdef", 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
