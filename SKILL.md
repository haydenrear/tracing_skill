---
name: tracing-observability
description: Use when instrumenting Python libraries or applications with standardized structured JSON logging, Prometheus metrics pushed through OTLP, local metrics debugging endpoints, and OpenTelemetry spans for the tracing-skill observability stack.
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

## Provides

- Importable Python package: `tracing_skill_observability`
- Structured JSON stdout logging with trace/span correlation
- OpenTelemetry span helpers and OTLP HTTP export
- Span annotation for sync and async Python functions
- Prometheus metrics helpers bridged to OTLP push, plus local debugging
  endpoints
- TOML config loading for application/library setup
- Helper CLI: `tracing-observability-install`

## Start Here

Use these Python references:

- [Structured logging](references/python/structured-logging.md):
  configure JSON stdout logs, standard log keys, and library logging
  expectations.
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
