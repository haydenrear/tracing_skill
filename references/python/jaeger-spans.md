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

## Create Spans With A Context Manager

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

## Create Spans With A Decorator

Use `@traced_span` when the whole function should run inside one span.
This works for synchronous and asynchronous functions.
If the wrapped function raises, the decorator records the exception on
the active span, marks the span status as `ERROR`, and re-raises the
original exception.

```python
from tracing_skill_observability import traced_span

@traced_span("load-order", component="orders")
def load_order(order_id: str):
    ...
```

You can omit the span name to use the function's module-qualified name:

```python
from tracing_skill_observability import traced_span

@traced_span
def publish_order_event(order_id: str):
    ...
```

Async functions are supported:

```python
from tracing_skill_observability import traced_span

@traced_span("fetch-price")
async def fetch_price(symbol: str):
    ...
```

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
