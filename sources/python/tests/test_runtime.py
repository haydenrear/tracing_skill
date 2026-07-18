import threading
import time
from types import SimpleNamespace

import tracing_skill_observability as observability
from opentelemetry.sdk.resources import Resource


def test_aggregate_configuration_is_default_on_idempotent_and_fail_open(
    monkeypatch,
):
    calls = []
    resources = []
    logging_attempts = 0

    def fail_logging(**kwargs):
        nonlocal logging_attempts
        calls.append("logging")
        resources.append(kwargs.get("resource"))
        logging_attempts += 1
        if logging_attempts == 1:
            raise RuntimeError("logs unavailable")

    def configure_tracing(**kwargs):
        calls.append("tracing")
        resources.append(kwargs.get("resource"))
        return SimpleNamespace(resource=kwargs.get("resource"))

    def start_metrics(**kwargs):
        calls.append("metrics")
        resources.append(kwargs.get("resource"))

    monkeypatch.setattr(observability, "_configured_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_requested_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_failed_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_aggregate_resource", None, raising=False)
    monkeypatch.setattr(observability, "configure_logging", fail_logging)
    monkeypatch.setattr(observability, "configure_tracing", configure_tracing)
    monkeypatch.setattr(observability, "configure_metrics", start_metrics)
    monkeypatch.setattr(observability, "force_flush_metrics", lambda **kwargs: True)
    monkeypatch.setattr(observability, "force_flush_logging", lambda **kwargs: True)
    monkeypatch.setattr(observability, "force_flush_tracing", lambda **kwargs: True)

    first = observability.configure_observability(
        service_name="runtime-test",
        metrics_enabled=False,
    )
    first_health = first.flush(timeout_millis=10)
    second = observability.configure_observability(
        service_name="ignored-second-call",
        metrics_enabled=True,
    )

    assert first is second
    assert isinstance(first, observability.ObservabilityHandle)
    assert first_health is False
    assert second.flush(timeout_millis=10) is True
    assert calls == ["tracing", "logging", "logging", "metrics"]
    assert all(resource is resources[0] for resource in resources)
    assert resources[0].attributes["service.name"] == "runtime-test"


def test_late_host_resource_conflict_is_unhealthy_then_converges(monkeypatch):
    provisional_resource = Resource.create({"service.name": "provisional"})
    host_resource = Resource.create(
        {"service.name": "host", "host.identity": "authoritative"}
    )
    tracing_attempts = 0
    logging_resources = []
    metric_providers = []

    def configure_tracing(**kwargs):
        nonlocal tracing_attempts
        tracing_attempts += 1
        if tracing_attempts == 1:
            raise RuntimeError("host provider not installed yet")
        return SimpleNamespace(resource=host_resource)

    def configure_logging(**kwargs):
        logging_resources.append(kwargs["resource"])
        return SimpleNamespace(resource=kwargs["resource"])

    def start_metrics(**kwargs):
        provider = SimpleNamespace(resource=kwargs["resource"])
        metric_providers.append(provider)
        return provider

    monkeypatch.setattr(observability, "_configured_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_requested_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_failed_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_aggregate_resource", None, raising=False)
    monkeypatch.setattr(
        observability,
        "create_observability_resource",
        lambda *args: provisional_resource,
    )
    monkeypatch.setattr(observability, "configure_tracing", configure_tracing)
    monkeypatch.setattr(observability, "configure_logging", configure_logging)
    monkeypatch.setattr(observability, "configure_metrics", start_metrics)
    monkeypatch.setattr(observability, "force_flush_metrics", lambda **kwargs: True)
    monkeypatch.setattr(observability, "force_flush_logging", lambda **kwargs: True)
    monkeypatch.setattr(observability, "force_flush_tracing", lambda **kwargs: True)

    handle = observability.configure_observability(metrics_enabled=False)
    assert handle.flush(timeout_millis=10) is False
    assert logging_resources == [provisional_resource]

    observability.configure_observability(metrics_enabled=True)
    assert handle.flush(timeout_millis=10) is False
    assert observability._aggregate_resource is host_resource
    assert logging_resources == [provisional_resource]
    assert metric_providers == []

    observability.configure_observability(metrics_enabled=True)

    assert handle.flush(timeout_millis=10) is True
    assert logging_resources == [provisional_resource, host_resource]
    assert [provider.resource for provider in metric_providers] == [host_resource]
    assert observability._configured_signals == {"tracing", "logging", "metrics"}
    assert observability._failed_signals == set()


def test_metric_setup_timeout_remains_unhealthy_until_retry(monkeypatch):
    resource = Resource.create({"service.name": "host"})
    metric_attempts = 0

    def start_metrics(**kwargs):
        nonlocal metric_attempts
        metric_attempts += 1
        if metric_attempts == 1:
            raise TimeoutError("metric provider setup timed out")
        return SimpleNamespace(resource=kwargs["resource"])

    monkeypatch.setattr(observability, "_configured_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_requested_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_failed_signals", set(), raising=False)
    monkeypatch.setattr(observability, "_aggregate_resource", None, raising=False)
    monkeypatch.setattr(
        observability,
        "configure_tracing",
        lambda **kwargs: SimpleNamespace(resource=resource),
    )
    monkeypatch.setattr(observability, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(observability, "configure_metrics", start_metrics)
    monkeypatch.setattr(observability, "force_flush_metrics", lambda **kwargs: False)
    monkeypatch.setattr(observability, "force_flush_logging", lambda **kwargs: True)
    monkeypatch.setattr(observability, "force_flush_tracing", lambda **kwargs: True)

    handle = observability.configure_observability(metrics_enabled=True)

    assert handle.flush(timeout_millis=10) is False
    assert "metrics" not in observability._configured_signals
    assert "metrics" in observability._failed_signals

    monkeypatch.setattr(observability, "force_flush_metrics", lambda **kwargs: True)
    observability.configure_observability(metrics_enabled=True)

    assert handle.flush(timeout_millis=10) is True
    assert "metrics" in observability._configured_signals
    assert "metrics" not in observability._failed_signals


def test_flush_skips_explicitly_disabled_metrics(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"logging", "tracing"},
        failed={"metrics"},
    )
    monkeypatch.setattr(
        observability,
        "force_flush_metrics",
        lambda **kwargs: calls.append("metrics") or False,
    )
    monkeypatch.setattr(
        observability,
        "force_flush_logging",
        lambda **kwargs: calls.append("logging") or True,
    )
    monkeypatch.setattr(
        observability,
        "force_flush_tracing",
        lambda **kwargs: calls.append("tracing") or True,
    )

    assert observability.flush_observability(timeout_millis=100) is True
    assert calls == ["logging", "tracing"]


def test_flush_attempts_all_requested_signals_after_setup_failure(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
        failed={"metrics"},
    )
    for signal, name in (
        ("metrics", "force_flush_metrics"),
        ("logging", "force_flush_logging"),
        ("tracing", "force_flush_tracing"),
    ):
        monkeypatch.setattr(
            observability,
            name,
            lambda *, timeout_millis, signal=signal: calls.append(signal) or True,
        )

    assert observability.flush_observability(timeout_millis=100) is False
    assert calls == ["metrics", "logging", "tracing"]


def test_flush_attempts_every_signal_and_never_raises(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
    )

    def fail_metrics(*, timeout_millis):
        calls.append(("metrics", timeout_millis))
        raise RuntimeError("metrics unavailable")

    def flush_logging(*, timeout_millis):
        calls.append(("logging", timeout_millis))
        return True

    def flush_tracing(*, timeout_millis):
        calls.append(("tracing", timeout_millis))
        return True

    monkeypatch.setattr(observability, "force_flush_metrics", fail_metrics)
    monkeypatch.setattr(observability, "force_flush_logging", flush_logging)
    monkeypatch.setattr(observability, "force_flush_tracing", flush_tracing)

    assert observability.flush_observability(timeout_millis=1234) is False
    assert [name for name, _ in calls] == ["metrics", "logging", "tracing"]
    timeouts = [timeout for _, timeout in calls]
    assert all(0 <= timeout <= 1234 for timeout in timeouts)
    assert timeouts == sorted(timeouts, reverse=True)


def test_flush_uses_one_monotonic_deadline_for_all_signals(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
    )

    def delayed_flush(name):
        def flush(*, timeout_millis):
            calls.append((name, timeout_millis))
            time.sleep(min(0.03, timeout_millis / 1_000))
            return timeout_millis > 0

        return flush

    monkeypatch.setattr(observability, "force_flush_metrics", delayed_flush("metrics"))
    monkeypatch.setattr(observability, "force_flush_logging", delayed_flush("logging"))
    monkeypatch.setattr(observability, "force_flush_tracing", delayed_flush("tracing"))

    started = time.monotonic()
    result = observability.flush_observability(timeout_millis=40)
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 0.075
    assert [name for name, _ in calls] == ["metrics", "logging"]
    assert calls[0][1] > calls[1][1]


def test_flush_uses_one_budget_sample_at_signal_boundary(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
    )
    clock_values = iter((10.0, 10.0, 10.0, 10.009, 10.011))
    last_clock_value = 10.011

    def monotonic():
        nonlocal last_clock_value
        last_clock_value = next(clock_values, last_clock_value)
        return last_clock_value

    monkeypatch.setattr(observability.time, "monotonic", monotonic)
    for signal, name in (
        ("metrics", "force_flush_metrics"),
        ("logging", "force_flush_logging"),
        ("tracing", "force_flush_tracing"),
    ):
        monkeypatch.setattr(
            observability,
            name,
            lambda *, timeout_millis, signal=signal: calls.append(
                (signal, timeout_millis)
            ),
        )

    assert observability.flush_observability(timeout_millis=10) is False
    assert calls == [("metrics", 1)]


def test_flush_skips_signal_when_sampled_budget_is_expired(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
    )
    clock_values = iter((20.0, 20.0, 20.0, 20.011))
    last_clock_value = 20.011

    def monotonic():
        nonlocal last_clock_value
        last_clock_value = next(clock_values, last_clock_value)
        return last_clock_value

    monkeypatch.setattr(observability.time, "monotonic", monotonic)
    for name in ("force_flush_metrics", "force_flush_logging", "force_flush_tracing"):
        monkeypatch.setattr(
            observability,
            name,
            lambda *, timeout_millis, signal=name: calls.append(
                (signal, timeout_millis)
            ),
        )

    assert observability.flush_observability(timeout_millis=10) is False
    assert calls == []


def test_flush_deadline_includes_configuration_lock_wait(monkeypatch):
    calls = []
    _set_signal_state(
        monkeypatch,
        requested={"metrics", "logging", "tracing"},
    )
    locked = threading.Event()
    release = threading.Event()

    def hold_configuration_lock():
        with observability._configure_lock:
            locked.set()
            release.wait(timeout=1)

    blocker = threading.Thread(target=hold_configuration_lock)
    blocker.start()
    assert locked.wait(timeout=1)
    release_timer = threading.Timer(0.2, release.set)
    release_timer.start()
    for name in ("force_flush_metrics", "force_flush_logging", "force_flush_tracing"):
        monkeypatch.setattr(
            observability,
            name,
            lambda *, timeout_millis, signal=name: calls.append(
                (signal, timeout_millis)
            ),
        )

    started = time.monotonic()
    try:
        result = observability.flush_observability(timeout_millis=10)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        release_timer.cancel()
        blocker.join(timeout=1)

    assert result is False
    assert elapsed < 0.1
    assert calls == []
    assert not blocker.is_alive()


def test_runtime_handle_delegates_to_public_trace_and_flush_contract(monkeypatch):
    expected = observability.TraceHandle("0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(observability, "current_trace_handle", lambda: expected)
    monkeypatch.setattr(observability, "current_trace_id", lambda: expected.trace_id)
    monkeypatch.setattr(observability, "flush_observability", lambda **kwargs: True)

    handle = observability.ObservabilityHandle()

    assert handle.trace_handle is expected
    assert handle.trace_id == expected.trace_id
    assert handle.flush(timeout_millis=10) is True


def _set_signal_state(monkeypatch, *, requested, failed=()):
    monkeypatch.setattr(
        observability,
        "_requested_signals",
        set(requested),
        raising=False,
    )
    monkeypatch.setattr(
        observability,
        "_failed_signals",
        set(failed),
        raising=False,
    )
