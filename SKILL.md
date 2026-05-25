---
name: tracing-observability
description: Use when instrumenting Python libraries or applications with standardized structured JSON logging, Prometheus metrics export, and OpenTelemetry spans for the tracing-skill observability stack.
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
- Span decorator for sync and async Python functions
- Prometheus metrics helpers and an ASGI `/metrics` app
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
- [Prometheus export](references/python/prometheus-export.md): expose
  `/metrics` for ASGI apps, start a standalone exporter for workers, and
  use standard HTTP metrics.

Minimal usage:

```python
from tracing_skill_observability import configure_observability, get_logger, traced_span

configure_observability(service_name="orders-api", service_version="0.1.0")
log = get_logger(__name__)

@traced_span("load-order", component="orders")
def load_order(order_id: str):
    log.info("order.loaded", extra={"order_id": "ord_123"})
```
