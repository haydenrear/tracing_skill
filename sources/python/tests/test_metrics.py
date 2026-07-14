from opentelemetry import trace
from opentelemetry.sdk.metrics.export import MetricExportResult
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from tracing_skill_observability import (
    PrometheusOtlpPusher,
    http_requests_total,
    metrics_app,
    trace_metric_labels,
)


class FakeMetricExporter:
    def __init__(self):
        self.exports = []

    def export(self, metrics_data):
        self.exports.append(metrics_data)
        return MetricExportResult.SUCCESS

    def shutdown(self):
        pass


def test_metrics_api_is_importable():
    http_requests_total.labels(method="GET", route="/health", status="200").inc()

    assert metrics_app() is not None


def test_trace_labeled_metric_is_exported_through_otlp():
    registry = CollectorRegistry()
    correlated = Counter(
        "correlation_events_total",
        "Events deliberately correlated to a trace.",
        ["trace_id", "result"],
        registry=registry,
    )
    trace_id = int("0123456789abcdef0123456789abcdef", 16)
    span_context = SpanContext(
        trace_id=trace_id,
        span_id=int("0123456789abcdef", 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    with trace.use_span(NonRecordingSpan(span_context)):
        correlated.labels(**trace_metric_labels(result="ok")).inc()

    exporter = FakeMetricExporter()
    pusher = PrometheusOtlpPusher(
        registry=registry,
        service_name="metrics-test",
        exporter=exporter,
    )

    assert pusher.export_once() == 1
    metric = exporter.exports[0].resource_metrics[0].scope_metrics[0].metrics[0]
    point = metric.data.data_points[0]
    assert metric.name == "correlation_events"
    assert point.attributes == {
        "trace_id": "0123456789abcdef0123456789abcdef",
        "result": "ok",
    }


def test_registry_types_are_preserved_in_otlp_data():
    registry = CollectorRegistry()
    depth = Gauge("queue_depth", "Queue depth.", ["queue"], registry=registry)
    depth.labels(queue="primary").set(3)
    depth.labels(queue="retry").set(1)
    latency = Histogram(
        "job_latency_seconds",
        "Job latency.",
        ["queue"],
        buckets=(1.0, 2.0),
        registry=registry,
    )
    latency.labels(queue="primary").observe(1.5)

    exporter = FakeMetricExporter()
    pusher = PrometheusOtlpPusher(registry=registry, exporter=exporter)

    assert pusher.export_once() == 2
    exported = {
        metric.name: metric
        for metric in exporter.exports[0].resource_metrics[0].scope_metrics[0].metrics
    }
    assert len(exported["queue_depth"].data.data_points) == 2
    histogram = exported["job_latency_seconds"].data.data_points[0]
    assert histogram.explicit_bounds == [1.0, 2.0]
    assert histogram.bucket_counts == [0, 1, 0]
    assert histogram.count == 1
    assert histogram.sum == 1.5
