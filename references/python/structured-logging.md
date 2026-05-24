# Python Structured Logging

Use this reference when a Python library or application needs
standardized JSON logs that can be collected from stdout and correlated
with OpenTelemetry traces.

## Install

Install the package into the target Python project:

```bash
tracing-observability-install --project /path/to/project
```

## Configure

Configure logging once near process startup:

```python
from tracing_skill_observability import configure_logging

configure_logging(service_name="orders-api", log_level="INFO")
```

Most applications should use the full observability setup instead:

```python
from tracing_skill_observability import configure_observability

configure_observability(service_name="orders-api", service_version="0.1.0")
```

You can also load shared config from TOML:

```toml
[observability]
service_name = "orders-api"
service_version = "0.1.0"
log_level = "INFO"
```

```python
from tracing_skill_observability import configure_observability_from_file

configure_observability_from_file("observability.toml")
```

## Log Records

Logs are written as one JSON object per line on stdout. The collector
expects application logs to be stdout/stderr text, not files inside the
container.

Standard keys:

- `timestamp`: UTC ISO timestamp.
- `severity`: Python logging level name.
- `logger`: logger name.
- `message`: rendered log message.
- `service_name`: configured service name.
- `trace_id`: active OpenTelemetry trace id, when present.
- `span_id`: active OpenTelemetry span id, when present.
- `exception`: formatted exception details when `exc_info` is present.

Any safe `extra={...}` fields passed to Python logging are included as
top-level keys:

```python
from tracing_skill_observability import get_logger

log = get_logger(__name__)
log.info("order.loaded", extra={"order_id": order_id, "tenant": tenant})
```

Prefer stable, low-cardinality keys. Avoid placing secrets, raw payloads,
or unbounded strings in structured fields.

## Library Guidance

Libraries should call `get_logger(__name__)` but should not call
`configure_logging()` themselves. Applications own process-level logging
configuration.
