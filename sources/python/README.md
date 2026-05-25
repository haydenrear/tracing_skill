# tracing-skill-observability

Importable Python package for standardized application observability:

- JSON logs on stdout for Kubernetes log collection.
- OpenTelemetry spans exported over OTLP HTTP.
- Prometheus metrics helpers and a standard `/metrics` ASGI app.
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
