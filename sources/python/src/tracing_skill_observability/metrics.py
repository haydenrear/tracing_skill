from __future__ import annotations

import logging
import math
import os
import time
from threading import Lock

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from ._resource import create_observability_resource
from .tracing import default_endpoint

_log = logging.getLogger(__name__)
_meter_provider_lock = Lock()
_meter_provider: MeterProvider | None = None
_trace_correlation_counter = None


def configure_metrics(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
    interval_seconds: float | None = None,
    resource: Resource | None = None,
) -> MeterProvider:
    """Configure one SDK-owned OTLP route or reuse the host's provider."""

    global _meter_provider

    if interval_seconds is not None and interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0")

    losing_candidate = None
    with _meter_provider_lock:
        if _meter_provider is not None:
            return _meter_provider

        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=_metrics_endpoint(otlp_endpoint)),
            export_interval_millis=(
                interval_seconds * 1_000
                if interval_seconds is not None
                else None
            ),
        )
        candidate = SdkMeterProvider(
            resource=(
                resource
                if resource is not None
                else _metrics_resource(service_name, service_version)
            ),
            metric_readers=[reader],
        )
        metrics.set_meter_provider(candidate)
        provider = metrics.get_meter_provider()
        if provider is not candidate:
            losing_candidate = candidate
        _meter_provider = provider

    if losing_candidate is not None:
        try:
            losing_candidate.shutdown()
        except Exception:
            _log.exception("observability.metrics.candidate_shutdown_failed")
    return provider


def get_meter(name: str | None = None, version: str | None = None) -> Meter:
    """Return a standard OpenTelemetry meter for application instruments."""

    return metrics.get_meter(
        name or os.getenv("OTEL_SERVICE_NAME") or "tracing-skill",
        version,
    )


def record_trace_correlation() -> bool:
    """Record the active trace on the package correlation Counter, fail open."""

    global _trace_correlation_counter

    try:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return False
        if _trace_correlation_counter is None:
            if not _meter_provider_lock.acquire(blocking=False):
                return False
            try:
                if _trace_correlation_counter is None:
                    _trace_correlation_counter = get_meter(
                        "tracing_skill_observability"
                    ).create_counter(
                        "tracing_observability.trace_correlation",
                        unit="{operation}",
                        description=(
                            "Bounded operations selected for trace correlation."
                        ),
                    )
            finally:
                _meter_provider_lock.release()
        _trace_correlation_counter.add(
            1,
            {"trace_id": format(span_context.trace_id, "032x")},
        )
        return True
    except Exception:
        _log.exception("observability.metrics.trace_correlation_failed")
        return False


def force_flush_metrics(timeout_millis: int = 5_000) -> bool:
    """Request public SDK flush completion without claiming backend delivery."""

    deadline = time.monotonic() + max(0, timeout_millis) / 1_000
    if not _meter_provider_lock.acquire(
        timeout=max(0.0, deadline - time.monotonic())
    ):
        return False
    try:
        provider = _meter_provider
    finally:
        _meter_provider_lock.release()
    if provider is None:
        return False
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        return False
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is None:
        return False
    try:
        return bool(
            force_flush(
                timeout_millis=math.ceil(remaining_seconds * 1_000),
            )
        )
    except Exception:
        _log.exception("observability.metrics.flush_failed")
        return False


def _metrics_resource(
    service_name: str | None,
    service_version: str | None,
) -> Resource:
    return create_observability_resource(service_name, service_version)


def _metrics_endpoint(otlp_endpoint: str | None) -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if explicit:
        return explicit
    base = (
        otlp_endpoint
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or default_endpoint("metrics")
    )
    return base if base.endswith("/v1/metrics") else f"{base.rstrip('/')}/v1/metrics"
