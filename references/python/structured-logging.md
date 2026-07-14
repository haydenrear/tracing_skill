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

The default `stdout` mode is intended for containers: Fluent Bit tails the
container stream and forwards each JSON line to Loki. Stdout is a dead end for
a bare-host process unless another agent is explicitly tailing it. Native
runners and local operator processes should opt into OTLP delivery:

```python
configure_logging(
    service_name="orders-worker",
    log_mode="otlp",
    logs_endpoint="http://localhost:4318/v1/logs",
)
```

Log delivery modes are explicit:

- `stdout` (default): write JSON to stdout only; use this in a container with
  Fluent Bit.
- `otlp`: write the same JSON line to stdout and export it over OTLP. `both` is
  an alias.
- `otlp-only`: export over OTLP without writing stdout.

Do not select `otlp` for a pod whose stdout is already collected by Fluent Bit:
the same record will reach Loki through both routes and be counted twice. Use
`stdout` there, or `otlp-only` when direct export is deliberately required.

The OTLP record body is byte-for-byte the JSON string written to stdout. The
gateway's raw Loki format therefore preserves the top-level `trace_id`, so the
same `| json | trace_id="<id>"` LogQL filter works for either route.

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
log_mode = "otlp"
logs_endpoint = "http://localhost:4318/v1/logs"
```

```python
from tracing_skill_observability import configure_observability_from_file

configure_observability_from_file("observability.toml")
```

## Log Records

Logs are formatted as one JSON object per line. In `stdout` and `otlp` mode the
line is written to stdout; in `otlp` and `otlp-only` mode that same string is the
OTLP log body.

The standard environment variables are also supported. `OTEL_LOGS_EXPORTER`
selects the mode (`none` retains stdout-only behavior),
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` sets the full logs endpoint, and
`OTEL_EXPORTER_OTLP_ENDPOINT` supplies a base URL to which `/v1/logs` is added.
An explicit `log_mode` or `logs_endpoint` argument takes precedence except for
the signal-specific standard endpoint variable.

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
