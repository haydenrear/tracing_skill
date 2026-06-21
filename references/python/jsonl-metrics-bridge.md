# Python JSONL Metrics Bridge

Use this reference when a Python process must publish Prometheus metrics
through a file instead of an HTTP scrape endpoint.

This mode exists for pass-through Kubernetes pods where the instrumented
service runs on a Mac or another host outside the cluster. In that
topology, code inside Kubernetes cannot call back to the Mac service over
REST, but both sides can see a JuiceFS-backed volume. The Mac-side
service writes registry snapshots to JSONL on the shared volume. A
pod-local daemon reads or tails that file and serves the metrics from an
in-cluster Prometheus endpoint.

Prefer normal `/metrics` export when the process runs inside the cluster
or can otherwise receive Prometheus scrape requests. Use the JSONL bridge
only when the network boundary prevents Kubernetes from reaching the
instrumented process directly.

## Configure

From Python:

```python
from tracing_skill_observability import configure_observability

configure_observability(
    service_name="orders-worker",
    metrics_jsonl_path="/shared/metrics/orders-worker.jsonl",
    metrics_jsonl_interval_seconds=5.0,
)
```

Equivalent TOML config:

```toml
[observability]
service_name = "orders-worker"
service_version = "0.1.0"
metrics_enabled = true
metrics_jsonl_path = "/shared/metrics/orders-worker.jsonl"
metrics_jsonl_interval_seconds = 5.0
```

The path parent directory is created automatically. The writer appends a
full registry snapshot on each interval. Use one file per service unless
the reader explicitly handles multiple services in one stream.

## Direct API

Use the direct writer APIs when an application needs explicit lifecycle
control:

```python
from tracing_skill_observability import start_metrics_jsonl_writer

writer = start_metrics_jsonl_writer(
    "/shared/metrics/orders-worker.jsonl",
    interval_seconds=5.0,
    service_name="orders-worker",
)

# Later, during controlled shutdown:
writer.stop()
```

For tests or one-shot exports:

```python
from tracing_skill_observability import write_metrics_jsonl_snapshot

write_metrics_jsonl_snapshot(
    "/shared/metrics/orders-worker.jsonl",
    service_name="orders-worker",
)
```

## Record Schema

Each line is one JSON object for one Prometheus sample:

```json
{"schema_version":1,"kind":"prometheus_sample","observed_at_unix_nano":1813574400000000000,"service_name":"orders-worker","metric_name":"orders_jobs","metric_type":"counter","sample_name":"orders_jobs_total","help":"Total order jobs processed.","labels":{"result":"ok"},"value":12.0}
```

Consumers should key the latest value by `service_name`, `sample_name`,
and `labels`. Periodic snapshots intentionally repeat samples. The
consumer should tolerate duplicate records and use the most recent
`observed_at_unix_nano` for a key.

Prometheus special numeric values that are not valid JSON numbers are
encoded as strings: `NaN`, `+Inf`, or `-Inf`.

## Pod-Side Serving

The pod-side daemon is responsible for reading the JSONL file from the
JuiceFS-mounted volume, retaining the latest sample values, and exposing
an in-cluster `/metrics` endpoint. The deployment, Service, and
ServiceMonitor wiring belongs to the deploy skill or the platform chart.

Do not make the pod daemon call the Mac service for metrics in this
topology. The file is the bridge across the Mac-to-cluster network
boundary.
