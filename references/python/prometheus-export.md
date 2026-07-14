# Python Prometheus Metrics over OTLP

Use this reference when Python services need metrics in the shared
monitoring cluster. The package keeps the normal `prometheus_client`
authoring API, periodically walks its registry, and pushes OTLP/HTTP to
the monitoring gateway. The gateway remote-writes those metrics into
Prometheus; nothing scrapes application endpoints in the production
fleet.

## Install

```bash
tracing-observability-install --project /path/to/project
```

## Configure Push Export

Configure observability once near application startup:

```python
from tracing_skill_observability import configure_observability

configure_observability(
    service_name="orders-worker",
    service_version="0.2.0",
    otlp_endpoint="http://localhost:4318",
)
```

The example above sets `otlp_endpoint` because a bare-host process has nothing
to inject one. **In a pod, pass no endpoint**: the chart injects
`OTEL_EXPORTER_OTLP_ENDPOINT` (`http://host.k3d.internal:4318`), and a literal
in your config would override it. `http://localhost:4318` is the default, so a
host process works unconfigured. The package also honors the metrics-specific
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`, which wins over both.

`deploy-helm:references/monitoring-cluster.md` is the source of truth for the
endpoints.

Prometheus retains **15 days, or 10GB**, whichever binds first. A series older
than that is absent because it expired, not because the push failed.

Equivalent TOML:

```toml
[observability]
service_name = "orders-worker"
service_version = "0.2.0"
otlp_endpoint = "http://localhost:4318"
metrics_enabled = true
metrics_export_interval_seconds = 15.0
```

For an isolated registry, start its pusher explicitly:

```python
from prometheus_client import CollectorRegistry
from tracing_skill_observability import start_metrics_otlp_pusher

registry = CollectorRegistry()
start_metrics_otlp_pusher(registry=registry, service_name="orders-worker")
```

## Trace-Correlated Metrics

`monitoring trace <id>` finds metrics by a `trace_id` metric label. A
metric without that label will not correlate. Add it only to a
deliberately scoped correlation metric:

```python
from prometheus_client import Counter
from tracing_skill_observability import trace_metric_labels

completed = Counter(
    "orders_completed_total",
    "Completed orders selected for trace correlation.",
    ["trace_id", "result"],
)

# Call inside an active span.
completed.labels(**trace_metric_labels(result="ok")).inc()
```

Trace IDs are inherently high-cardinality. Do not add `trace_id` to
broad operational series such as `http_requests_total`; keep ordinary
traffic metrics low-cardinality and use the label only where cross-signal
correlation is the purpose.

## Standard HTTP Metrics

The package exposes a low-cardinality counter and histogram:

```python
from tracing_skill_observability import http_request_duration, http_requests_total

route = "/orders/{id}"
status = "200"

http_requests_total.labels(method="GET", route=route, status=status).inc()
with http_request_duration.labels(method="GET", route=route, status=status).time():
    handle_request()
```

Use route templates such as `/orders/{id}`, not raw request paths.

## Local Debugging Endpoints

`metrics_app()` and `start_metrics_server()` expose the registry for
local inspection. They are debugging affordances, not production export
paths: the pure-push monitoring fleet does not scrape them.

```python
from tracing_skill_observability import metrics_app, start_metrics_server

app.mount("/metrics", metrics_app())
start_metrics_server(9464)
```
