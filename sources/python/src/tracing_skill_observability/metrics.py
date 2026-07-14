from __future__ import annotations

import atexit
import logging
import math
import os
import threading
import time
from collections import defaultdict
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    Gauge,
    Histogram as OtlpHistogram,
    HistogramDataPoint,
    Metric,
    MetricExportResult,
    MetricsData,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
    Sum,
)
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    make_asgi_app,
    start_http_server,
)

_log = logging.getLogger(__name__)

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "route", "status"],
)

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route", "status"],
)


def metrics_app(registry: CollectorRegistry = REGISTRY):
    """Return a Prometheus scrape app for local debugging."""

    return make_asgi_app(registry=registry)


def start_metrics_server(
    port: int = 9464,
    addr: str = "0.0.0.0",
    registry: CollectorRegistry = REGISTRY,
) -> None:
    """Start a local debugging endpoint; production metrics use OTLP push."""

    start_http_server(port, addr=addr, registry=registry)


def trace_metric_labels(**labels: str) -> dict[str, str]:
    """Add the active span's trace ID for a deliberately correlated metric."""

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        raise RuntimeError("trace_metric_labels requires an active valid span")
    return {**labels, "trace_id": format(span_context.trace_id, "032x")}


class PrometheusOtlpPusher:
    """Periodically export a Prometheus registry through OTLP/HTTP."""

    def __init__(
        self,
        *,
        interval_seconds: float = 15.0,
        registry: CollectorRegistry = REGISTRY,
        service_name: str | None = None,
        service_version: str | None = None,
        otlp_endpoint: str | None = None,
        exporter: Any | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        self.interval_seconds = interval_seconds
        self.registry = registry
        self.resource = _metrics_resource(service_name, service_version)
        self.exporter = exporter or OTLPMetricExporter(
            endpoint=_metrics_endpoint(otlp_endpoint)
        )
        self._start_time_unix_nano = time.time_ns()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> PrometheusOtlpPusher:
        if self.is_running:
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="prometheus-otlp-pusher",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self.exporter.shutdown()

    def export_once(self) -> int:
        metrics = _collect_otlp_metrics(
            self.registry,
            start_time_unix_nano=self._start_time_unix_nano,
        )
        if not metrics:
            return 0
        data = MetricsData(
            resource_metrics=[
                ResourceMetrics(
                    resource=self.resource,
                    scope_metrics=[
                        ScopeMetrics(
                            scope=InstrumentationScope(
                                "tracing_skill_observability.prometheus"
                            ),
                            metrics=metrics,
                            schema_url="",
                        )
                    ],
                    schema_url="",
                )
            ]
        )
        if self.exporter.export(data) is not MetricExportResult.SUCCESS:
            raise RuntimeError("OTLP metric export failed")
        return len(metrics)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.export_once()
            except Exception:
                _log.exception("metrics_otlp.export_failed")
            self._stop_event.wait(self.interval_seconds)


_metrics_otlp_pushers: list[PrometheusOtlpPusher] = []
_metrics_otlp_pushers_lock = threading.Lock()


def start_metrics_otlp_pusher(
    *,
    interval_seconds: float = 15.0,
    registry: CollectorRegistry = REGISTRY,
    service_name: str | None = None,
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
) -> PrometheusOtlpPusher:
    """Start periodic OTLP push for a Prometheus registry."""

    pusher = PrometheusOtlpPusher(
        interval_seconds=interval_seconds,
        registry=registry,
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
    ).start()
    with _metrics_otlp_pushers_lock:
        _metrics_otlp_pushers.append(pusher)
    return pusher


def _stop_metrics_otlp_pushers() -> None:
    with _metrics_otlp_pushers_lock:
        pushers = list(_metrics_otlp_pushers)
        _metrics_otlp_pushers.clear()
    for pusher in pushers:
        pusher.stop(timeout=1.0)


def _collect_otlp_metrics(
    registry: CollectorRegistry,
    *,
    start_time_unix_nano: int,
) -> list[Metric]:
    now = time.time_ns()
    metrics: list[Metric] = []
    for family in registry.collect():
        if family.type == "counter":
            points = [
                _number_point(sample, start_time_unix_nano, now)
                for sample in family.samples
                if sample.name.endswith("_total")
            ]
            if points:
                metrics.append(
                    Metric(
                        name=family.name,
                        description=family.documentation,
                        unit=family.unit or "",
                        data=Sum(
                            data_points=points,
                            aggregation_temporality=AggregationTemporality.CUMULATIVE,
                            is_monotonic=True,
                        ),
                    )
                )
        elif family.type == "histogram":
            metrics.extend(
                _histogram_metrics(family, start_time_unix_nano, now)
            )
        else:
            sample_groups: dict[str, list[NumberDataPoint]] = defaultdict(list)
            for sample in family.samples:
                if sample.name.endswith("_created"):
                    continue
                sample_groups[sample.name].append(
                    _number_point(sample, start_time_unix_nano, now)
                )
            for sample_name, points in sample_groups.items():
                metrics.append(
                    Metric(
                        name=sample_name,
                        description=family.documentation,
                        unit=family.unit or "",
                        data=Gauge(data_points=points),
                    )
                )
    return metrics


def _histogram_metrics(
    family: Any,
    start_time_unix_nano: int,
    now: int,
) -> list[Metric]:
    groups: dict[tuple[tuple[str, str], ...], dict[str, Any]] = defaultdict(dict)
    for sample in family.samples:
        labels = {key: value for key, value in sample.labels.items() if key != "le"}
        group = groups[tuple(sorted(labels.items()))]
        group["labels"] = labels
        if sample.name.endswith("_bucket"):
            group.setdefault("buckets", []).append(
                (float(sample.labels["le"]), int(sample.value))
            )
        elif sample.name.endswith("_count"):
            group["count"] = int(sample.value)
        elif sample.name.endswith("_sum"):
            group["sum"] = float(sample.value)

    points: list[HistogramDataPoint] = []
    for group in groups.values():
        buckets = sorted(group.get("buckets", []), key=lambda item: item[0])
        cumulative_counts = [count for _, count in buckets]
        bucket_counts = [
            count - (cumulative_counts[index - 1] if index else 0)
            for index, count in enumerate(cumulative_counts)
        ]
        explicit_bounds = [bound for bound, _ in buckets if math.isfinite(bound)]
        points.append(
            HistogramDataPoint(
                attributes=group["labels"],
                start_time_unix_nano=start_time_unix_nano,
                time_unix_nano=now,
                count=group.get("count", cumulative_counts[-1] if buckets else 0),
                sum=group.get("sum", 0.0),
                bucket_counts=bucket_counts,
                explicit_bounds=explicit_bounds,
                min=None,  # type: ignore[arg-type]
                max=None,  # type: ignore[arg-type]
            )
        )
    if not points:
        return []
    return [
        Metric(
            name=family.name,
            description=family.documentation,
            unit=family.unit or "",
            data=OtlpHistogram(
                data_points=points,
                aggregation_temporality=AggregationTemporality.CUMULATIVE,
            ),
        )
    ]


def _number_point(sample: Any, start_time_unix_nano: int, now: int) -> NumberDataPoint:
    return NumberDataPoint(
        attributes=dict(sample.labels),
        start_time_unix_nano=start_time_unix_nano,
        time_unix_nano=now,
        value=sample.value,
    )


def _metrics_resource(
    service_name: str | None,
    service_version: str | None,
) -> Resource:
    attributes: dict[str, str] = {}
    service = service_name or os.getenv("OTEL_SERVICE_NAME")
    if service:
        attributes[SERVICE_NAME] = service
    if service_version:
        attributes[SERVICE_VERSION] = service_version
    if os.getenv("DEPLOYMENT_ENVIRONMENT"):
        attributes[DEPLOYMENT_ENVIRONMENT] = os.environ["DEPLOYMENT_ENVIRONMENT"]
    return Resource.create(attributes)


def _metrics_endpoint(otlp_endpoint: str | None) -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if explicit:
        return explicit
    base = (
        otlp_endpoint
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or "http://localhost:4318"
    )
    return base if base.endswith("/v1/metrics") else f"{base.rstrip('/')}/v1/metrics"


atexit.register(_stop_metrics_otlp_pushers)
