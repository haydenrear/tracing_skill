# Python OpenTelemetry Metrics over OTLP

Use this reference when Python services need metrics in the shared monitoring
cluster. Applications author standard OpenTelemetry instruments. When no host
provider exists, `tracing_skill_observability` installs one `MeterProvider`
with one `PeriodicExportingMetricReader` and `OTLPMetricExporter`.

## Configure Metrics Export

Configure observability once near application startup:

```python
from tracing_skill_observability import configure_observability

configure_observability(
    service_name="orders-worker",
    service_version="0.3.0",
)
```

In a pod, pass no endpoint: the chart injects
`OTEL_EXPORTER_OTLP_ENDPOINT=http://host.k3d.internal:4318`. A bare-host process
defaults to `http://localhost:4318`. The metrics-specific
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` wins over the function argument and
general environment variable.

Endpoint precedence is signal-specific environment variable, explicit
argument, general environment variable, then the localhost fallback. An
explicit `metrics_export_interval_seconds` wins over
`OTEL_METRIC_EXPORT_INTERVAL`; when it is omitted, the reader uses that
standard environment variable and SDK default. An aggregate-provided resource
wins outright. Otherwise an explicit `service_name` wins over
`OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES`; OpenTelemetry resource
detectors supply attributes not explicitly set.

Equivalent TOML:

```toml
[observability]
service_name = "orders-worker"
service_version = "0.3.0"
metrics_enabled = true
metrics_export_interval_seconds = 15.0
```

If the host already installed a real provider, the package uses it without
adding or inspecting readers. In that case the host owns export and lifecycle;
configuration does not claim its transport, resource identity, scraping
behavior, delivery, flush result, or backend reachability.

## Author Standard Instruments

Use `get_meter()` and the OpenTelemetry Metrics API directly:

```python
from tracing_skill_observability import get_meter

meter = get_meter("orders")
completed = meter.create_counter(
    "orders.completed",
    unit="{order}",
    description="Completed orders.",
)
duration = meter.create_histogram(
    "orders.duration",
    unit="s",
    description="Order processing duration.",
)

completed.add(1, {"result": "ok"})
duration.record(0.042, {"result": "ok"})
```

Use low-cardinality attributes and bounded values such as route templates.
Create asynchronous gauges through standard ObservableGauge callbacks; the
package does not own mutable gauge state.

## Trace Correlation

The package owns one correlation Counter named
`tracing_observability.trace_correlation`. `span(...)` and `@traced_span`
record it once when their bounded span begins. If a host creates a bounded span
directly, call the fail-open API once inside it:

```python
from tracing_skill_observability import get_tracer, record_trace_correlation

with get_tracer().start_as_current_span("orders.dispatch"):
    record_trace_correlation()
    dispatch_order()
```

This Counter is the only package instrument with a `trace_id` attribute. Never
add trace IDs to broad operational instruments.

## Finite Processes

`ObservabilityHandle.flush()` requests the standard SDK flush alongside logs
and traces:

```python
observability.flush(timeout_millis=5_000)
```

The result reports only surfaced SDK completion. It does not promise exporter
or backend acknowledgement. For an externally managed provider, the host
defines the meaning of its public flush result. Failures are logged and remain
fail-open.
