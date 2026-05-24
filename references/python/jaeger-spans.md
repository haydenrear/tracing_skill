# Python Jaeger Spans

Use this reference when Python code needs trace spans that appear in
Jaeger through the platform OpenTelemetry Collector.

## Install

```bash
tracing-observability-install --project /path/to/project
```

## Configure

Configure tracing once near application startup:

```python
from tracing_skill_observability import configure_tracing

configure_tracing(
    service_name="orders-api",
    service_version="0.1.0",
    otlp_endpoint="http://cdc-commit-diff-context-otel-collector.cdc.svc:4318",
)
```

Most services should use the combined setup:

```python
from tracing_skill_observability import configure_observability

configure_observability(
    service_name="orders-api",
    service_version="0.1.0",
    otlp_endpoint="http://cdc-commit-diff-context-otel-collector.cdc.svc:4318",
)
```

The library also honors:

- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- `DEPLOYMENT_ENVIRONMENT`

## Create Spans

Use spans around meaningful operations: external calls, queue handling,
database work, expensive local computation, and business workflow steps.

```python
from tracing_skill_observability import span

with span("load-order", order_id=order_id):
    order = load_order(order_id)
```

Span attributes should be useful for filtering and debugging:

```python
with span(
    "publish-event",
    topic="orders.created",
    tenant=tenant,
    order_id=order_id,
):
    publish_event(order)
```

Avoid secrets, raw payloads, large documents, and high-cardinality fields
that are not needed for debugging.

## Logs And Spans

When logs are emitted inside an active span, the JSON log formatter adds
`trace_id` and `span_id`. This makes it possible to move from a log line
to the corresponding trace.

```python
from tracing_skill_observability import get_logger, span

log = get_logger(__name__)

with span("reprice-position", position_id=position_id):
    log.info("position.reprice.started", extra={"position_id": position_id})
```

## Jaeger

Jaeger is expected to be exposed by the platform through nginx TCP.
Use the platform-provided URL:

```text
http://<nginx-host>:16686
```
