import json
import time
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge

from tracing_skill_observability import (
    http_requests_total,
    metrics_app,
    start_metrics_jsonl_writer,
    write_metrics_jsonl_snapshot,
)


def test_metrics_api_is_importable():
    http_requests_total.labels(method="GET", route="/health", status="200").inc()

    assert metrics_app() is not None


def test_write_metrics_jsonl_snapshot(tmp_path: Path):
    registry = CollectorRegistry()
    requests_total = Counter(
        "bridge_requests_total",
        "Bridge requests.",
        ["status"],
        registry=registry,
    )
    requests_total.labels(status="ok").inc(3)

    output_path = tmp_path / "metrics.jsonl"
    count = write_metrics_jsonl_snapshot(
        output_path,
        registry=registry,
        service_name="bridge",
    )

    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    request_record = next(
        record for record in records if record["sample_name"] == "bridge_requests_total"
    )

    assert count == len(records)
    assert request_record["schema_version"] == 1
    assert request_record["kind"] == "prometheus_sample"
    assert request_record["service_name"] == "bridge"
    assert request_record["metric_name"] == "bridge_requests"
    assert request_record["metric_type"] == "counter"
    assert request_record["help"] == "Bridge requests."
    assert request_record["labels"] == {"status": "ok"}
    assert request_record["value"] == 3.0


def test_start_metrics_jsonl_writer_writes_snapshot(tmp_path: Path):
    registry = CollectorRegistry()
    queue_depth = Gauge(
        "bridge_queue_depth",
        "Bridge queue depth.",
        registry=registry,
    )
    queue_depth.set(7)
    output_path = tmp_path / "metrics.jsonl"

    writer = start_metrics_jsonl_writer(
        output_path,
        interval_seconds=60.0,
        registry=registry,
        service_name="bridge",
    )
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if output_path.exists() and output_path.read_text().strip():
                break
            time.sleep(0.01)
    finally:
        writer.stop()

    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    queue_record = next(
        record for record in records if record["sample_name"] == "bridge_queue_depth"
    )

    assert queue_record["service_name"] == "bridge"
    assert queue_record["value"] == 7.0
