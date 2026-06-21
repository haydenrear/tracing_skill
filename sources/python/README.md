# tracing-skill-observability

Importable Python package for standardized application observability:

- JSON logs on stdout for Kubernetes log collection.
- OpenTelemetry spans exported over OTLP HTTP.
- Prometheus metrics helpers and a standard `/metrics` ASGI app.
- JSONL metrics snapshots for pass-through Kubernetes pods that need to
  sync metrics through a shared file and serve Prometheus inside the pod.
- Trace and span ids injected into log records emitted inside active
  spans.

```python
from tracing_skill_observability import (
    configure_observability,
    get_logger,
    http_request_duration,
    metrics_app,
    span,
)

configure_observability(service_name="orders-api", service_version="0.1.0")
log = get_logger(__name__)

with span("load-order", order_id="ord_123"):
    log.info("order.loaded", extra={"order_id": "ord_123"})
```

For FastAPI:

```python
from fastapi import FastAPI
from tracing_skill_observability import configure_observability, metrics_app

app = FastAPI()
configure_observability(service_name="orders-api")
app.mount("/metrics", metrics_app())
```

Or configure from TOML:

```toml
[observability]
service_name = "orders-api"
service_version = "0.1.0"
otlp_endpoint = "http://cdc-commit-diff-context-otel-collector.cdc.svc:4318"
log_level = "INFO"
```

```python
from tracing_skill_observability import configure_observability_from_file

configure_observability_from_file("observability.toml")
```

Structured log keys are `timestamp`, `severity`, `logger`, `message`,
`service_name`, `trace_id`, `span_id`, any safe `extra` fields, and
`exception` when exception info is present.

Use `@traced_span` when a whole function should run inside a span:

```python
from tracing_skill_observability import traced_span

@traced_span("load-order", component="orders")
def load_order(order_id: str):
    ...
```

Metrics use the official `prometheus_client` package. You can use native
Prometheus client counters, histograms, registries, and timing
decorators alongside this package's helpers.

For pass-through Kubernetes pods where the instrumented service runs on a
Mac outside the cluster, write snapshots to a JuiceFS-backed JSONL file
instead of relying on cluster-to-Mac requests:

```toml
[observability]
service_name = "orders-worker"
metrics_enabled = true
metrics_jsonl_path = "/shared/metrics/orders-worker.jsonl"
metrics_jsonl_interval_seconds = 5.0
```

The pod-side daemon can read the JSONL stream from the mounted volume and
serve the latest sample values from an in-cluster `/metrics` endpoint.
