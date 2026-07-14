---
name: tracing-observability
description: Use when instrumenting Python libraries or applications with standardized structured JSON logging, OpenTelemetry spans, and Prometheus metrics, all pushed over OTLP to the shared monitoring cluster, plus local metrics debugging endpoints.
skill-imports: []
metadata:
  focus: client-side-python-instrumentation
  package: tracing-skill-observability
  import_module: tracing_skill_observability
  source: sources/python
  references:
    - references/python/structured-logging.md
    - references/python/jaeger-spans.md
    - references/python/prometheus-export.md
---

# tracing-observability

Use this skill for client-side Python instrumentation. Deployment and
cluster operations are handled by the deploy skill, not this skill.

## Where Telemetry Goes

Every signal — spans, logs, and metrics — is pushed over OTLP to the OTel
gateway on the **shared monitoring cluster**, which fans out to Jaeger,
Loki, and Prometheus. It is deployed once and pointed at thereafter;
nothing is stored on a service cluster, and nothing scrapes your app.

| Caller | OTLP/HTTP base |
| --- | --- |
| A service pod | `http://host.k3d.internal:4318` |
| The host (tests, native runners) | `http://localhost:4318` |

In a pod the chart injects `OTEL_EXPORTER_OTLP_ENDPOINT`, so **you
normally configure no endpoint at all**; set one explicitly only for a
bare-host process. `deploy-helm:references/monitoring-cluster.md` is the
source of truth for the endpoints, the `monitoring` CLI, and retention.
Use `monitoring trace <id>` to see a trace across all three signals.

## Provides

- Importable Python package: `tracing_skill_observability`
- Structured JSON logging with trace/span correlation, delivered through
  container stdout or direct OTLP HTTP export
- OpenTelemetry span helpers and OTLP HTTP export
- Span annotation for sync and async Python functions
- Prometheus metrics helpers bridged to OTLP push, plus local debugging
  endpoints
- TOML config loading for application/library setup
- Helper CLI: `tracing-observability-install`

## Start Here

Use these Python references:

- [Structured logging](references/python/structured-logging.md):
  configure JSON stdout/OTLP delivery modes, standard log keys, and library
  logging expectations for containers and bare-host processes.
- [Jaeger spans](references/python/jaeger-spans.md): configure OTLP
  tracing, create spans, attach useful attributes, and correlate logs
  with traces.
- [Prometheus export](references/python/prometheus-export.md): push a
  Prometheus registry to the monitoring gateway over OTLP, create
  deliberately trace-correlated metrics, and use local `/metrics`
  endpoints for debugging.

## Span Rules

- Prefer the library-provided `@traced_span` annotation for function
  instrumentation. It records exceptions on the span, marks failures as
  `ERROR`, and re-raises the original exception.
- Do not create a local tracing decorator, wrapper, fallback, shim, or
  guard around `traced_span`. Assume `tracing_skill_observability` is an
  available dependency when this skill is being used.
- Do not replace `@traced_span` with a `span(...)` context manager for a
  whole function. Use the context manager only for short inner operations
  when annotating the whole function would exceed the span duration rule.
- Every span should represent work expected to finish in less than 1
  second. Do not wrap long-running loops, servers, daemons, pollers,
  watches, consumers, training runs, migrations, or batch jobs in one
  span. Instead, span individual iterations, requests, messages, queries,
  chunks, or other bounded operations.

Minimal usage:

```python
from tracing_skill_observability import configure_observability, get_logger, traced_span

configure_observability(service_name="orders-api", service_version="0.1.0")
log = get_logger(__name__)

@traced_span("load-order", component="orders")
def load_order(order_id: str):
    log.info("order.loaded", extra={"order_id": "ord_123"})
```
