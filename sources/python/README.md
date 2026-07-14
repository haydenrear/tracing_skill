# tracing-skill-observability

Importable Python package for standardized application observability. Every
signal is pushed over OTLP to the OTel gateway on the shared monitoring
cluster, which fans out to Jaeger, Loki, and Prometheus.

- JSON logs on stdout for Kubernetes collection, or pushed directly over OTLP
  from bare-host processes.
- OpenTelemetry spans exported over OTLP HTTP.
- Prometheus metrics helpers exported to the monitoring gateway over
  OTLP HTTP, with optional local debugging endpoints.
- Trace and span ids injected into log records emitted inside active
  spans.

## Endpoint

| Caller | OTLP/HTTP base |
| --- | --- |
| A service pod | `http://host.k3d.internal:4318` |
| The host (tests, native runners) | `http://localhost:4318` |

In a pod the chart injects `OTEL_EXPORTER_OTLP_ENDPOINT`, so configure **no**
endpoint — a literal in your config would override the right answer with a
stale one. `http://localhost:4318` is the default, so a bare-host process works
unconfigured; an unconfigured pod logs a warning naming the variable to set.
See `deploy-helm:references/monitoring-cluster.md` for the source of truth.

Upgrade note: version 0.2 removes the public shared-file metric writer and
its configuration keys. Configure OTLP push as shown below instead.

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
log_level = "INFO"
log_mode = "stdout"
```

```python
from tracing_skill_observability import configure_observability_from_file

configure_observability_from_file("observability.toml")
```

Structured log keys are `timestamp`, `severity`, `logger`, `message`,
`service_name`, `trace_id`, `span_id`, any safe `extra` fields, and
`exception` when exception info is present.

Logging defaults to `stdout`, which is the correct route for pods collected by
Fluent Bit. A process running on the bare host should use `log_mode="otlp"` to
print and export, or `log_mode="otlp-only"` to export without printing. `both`
is an alias for `otlp`. Do not use print-and-export mode in a collected pod or
the record will reach Loki twice. Set `logs_endpoint` (or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`) to the full `/v1/logs` endpoint; the general
`otlp_endpoint`/`OTEL_EXPORTER_OTLP_ENDPOINT` base is used as a fallback.

Use `@traced_span` when a whole function should run inside a span:

```python
from tracing_skill_observability import traced_span

@traced_span("load-order", component="orders")
def load_order(order_id: str):
    ...
```

Metrics use the official `prometheus_client` package. You can use native
Prometheus client counters, histograms, registries, and timing
decorators alongside this package's helpers. `configure_observability()`
periodically pushes the default registry to the configured OTLP gateway.

Set the gateway base URL only where nothing injects it. The OTLP exporter adds
`/v1/metrics` automatically:

```toml
[observability]
service_name = "orders-worker"
metrics_enabled = true
otlp_endpoint = "http://localhost:4318"
metrics_export_interval_seconds = 15.0
```

`metrics_app()` and `metrics_port` remain available only for local
scrape/debugging use; the production fleet does not scrape them.

Trace correlation is deliberately opt-in because trace IDs are
high-cardinality. Declare `trace_id` only on narrowly scoped correlation
metrics, then populate it from the active span:

```python
from prometheus_client import Counter
from tracing_skill_observability import trace_metric_labels

completed = Counter(
    "orders_completed_total",
    "Completed orders selected for trace correlation.",
    ["trace_id", "result"],
)
completed.labels(**trace_metric_labels(result="ok")).inc()
```

A metric without the `trace_id` label is intentionally absent from
`monitoring trace <id>`. Never add `trace_id` to broad traffic metrics
such as `http_requests_total`.
