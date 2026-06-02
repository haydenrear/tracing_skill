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

## Span Duration Rule

Every span should represent work expected to complete in less than 1
second. Do not create spans around long-running loops, servers, daemons,
pollers, watches, consumers, training runs, migrations, or whole batch
jobs. For those workflows, create spans around bounded units of work such
as one request, one message, one query, one retry, one chunk, or one loop
iteration.

If an operation commonly takes longer than 1 second, either split it into
smaller spans or use logs and metrics instead of one long span.

## Create Function Spans With The Annotation

Use the library-provided `@traced_span` annotation for function
instrumentation. This works for synchronous and asynchronous functions.
If the wrapped function raises, the annotation records the exception on
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

Do not create a local tracing decorator, wrapper, fallback, shim, or
guard around `traced_span`. Assume `tracing_skill_observability` is
installed and importable when this skill is being used.

Do not replace `@traced_span` with a `span(...)` context manager for a
whole function. Use `@traced_span` so exceptions are recorded as span
errors and propagated normally.

## Create Short Inner Spans With A Context Manager

Use `span(...)` only for short inner operations when the whole function is
too broad or could exceed the 1-second span duration rule. Good examples
are external calls, queue message handling, database queries, expensive
local computation blocks, and bounded business workflow steps.

```python
from tracing_skill_observability import span

with span("load-order-query", order_id=order_id):
    order = load_order_query(order_id)
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
from tracing_skill_observability import get_logger, traced_span

log = get_logger(__name__)

@traced_span("reprice-position", component="positions")
def reprice_position(position_id: str):
    log.info("position.reprice.started", extra={"position_id": position_id})
```

## Jaeger

Jaeger is expected to be exposed by the platform through nginx TCP.
Use the platform-provided URL:

```text
http://<nginx-host>:16686
```
