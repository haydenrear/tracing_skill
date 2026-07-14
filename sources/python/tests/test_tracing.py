import asyncio
import logging
from contextlib import contextmanager

import pytest

from tracing_skill_observability import traced_span
from tracing_skill_observability import tracing

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


def test_default_endpoint_warns_once_when_nothing_configured(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="tracing_skill_observability.tracing"):
        first = tracing.default_endpoint("traces")
        second = tracing.default_endpoint("traces")

    assert first == second == tracing.DEFAULT_OTLP_ENDPOINT
    assert [record.message for record in caplog.records] == ["observability.endpoint.defaulted"]


def test_trace_endpoint_falls_back_to_the_default():
    assert tracing._trace_endpoint(None) == "http://localhost:4318/v1/traces"


def test_trace_endpoint_prefers_explicit_argument_over_default():
    assert (
        tracing._trace_endpoint("http://host.k3d.internal:4318")
        == "http://host.k3d.internal:4318/v1/traces"
    )


def test_trace_endpoint_prefers_explicit_argument_over_base_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://base:4318")

    assert tracing._trace_endpoint("http://arg:4318") == "http://arg:4318/v1/traces"


def test_trace_endpoint_uses_base_env_when_no_argument(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://host.k3d.internal:4318")

    assert tracing._trace_endpoint(None) == "http://host.k3d.internal:4318/v1/traces"


def test_signal_env_var_overrides_argument_and_base_env(monkeypatch: pytest.MonkeyPatch):
    """The signal-specific variable wins outright, matching logs and metrics.

    It is the last word deliberately: it is how an operator redirects one signal
    of an already-configured process without editing it.
    """

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://base:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://signal:4318/v1/traces")

    assert tracing._trace_endpoint("http://arg:4318") == "http://signal:4318/v1/traces"


def test_trace_endpoint_does_not_double_append_the_signal_path():
    assert (
        tracing._trace_endpoint("http://localhost:4318/v1/traces")
        == "http://localhost:4318/v1/traces"
    )


def test_trace_endpoint_tolerates_a_trailing_slash():
    assert tracing._trace_endpoint("http://localhost:4318/") == "http://localhost:4318/v1/traces"


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
    def start_as_current_span(self, name):
        yield self.span
