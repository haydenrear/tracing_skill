from __future__ import annotations

import atexit
import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    make_asgi_app,
    start_http_server,
)

_log = logging.getLogger(__name__)

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "route", "status"],
)

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route", "status"],
)


def metrics_app(registry: CollectorRegistry = REGISTRY):
    return make_asgi_app(registry=registry)


def start_metrics_server(
    port: int = 9464,
    addr: str = "0.0.0.0",
    registry: CollectorRegistry = REGISTRY,
) -> None:
    start_http_server(port, addr=addr, registry=registry)


def iter_metrics_jsonl_records(
    registry: CollectorRegistry = REGISTRY,
    *,
    service_name: str | None = None,
    observed_at_unix_nano: int | None = None,
) -> Iterator[dict[str, Any]]:
    observed_at = (
        observed_at_unix_nano if observed_at_unix_nano is not None else time.time_ns()
    )
    for metric in registry.collect():
        for sample in metric.samples:
            record: dict[str, Any] = {
                "schema_version": 1,
                "kind": "prometheus_sample",
                "observed_at_unix_nano": observed_at,
                "metric_name": metric.name,
                "metric_type": metric.type,
                "sample_name": sample.name,
                "help": metric.documentation,
                "labels": dict(sample.labels),
                "value": _json_metric_value(sample.value),
            }
            if service_name is not None:
                record["service_name"] = service_name
            unit = getattr(metric, "unit", "")
            if unit:
                record["unit"] = unit
            timestamp = getattr(sample, "timestamp", None)
            if timestamp is not None:
                record["sample_timestamp"] = timestamp
            exemplar = _json_exemplar(getattr(sample, "exemplar", None))
            if exemplar is not None:
                record["exemplar"] = exemplar
            yield record


def write_metrics_jsonl_snapshot(
    path: str | Path,
    *,
    registry: CollectorRegistry = REGISTRY,
    service_name: str | None = None,
) -> int:
    records = list(
        iter_metrics_jsonl_records(registry=registry, service_name=service_name)
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        output_path.touch()
        return 0

    with output_path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, allow_nan=False, separators=(",", ":"), sort_keys=True)
            )
            stream.write("\n")
    return len(records)


class MetricsJsonlWriter:
    def __init__(
        self,
        path: str | Path,
        *,
        interval_seconds: float = 5.0,
        registry: CollectorRegistry = REGISTRY,
        service_name: str | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        self.path = Path(path)
        self.interval_seconds = interval_seconds
        self.registry = registry
        self.service_name = service_name
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> MetricsJsonlWriter:
        if self.is_running:
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"metrics-jsonl-writer:{self.path}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def write_once(self) -> int:
        return write_metrics_jsonl_snapshot(
            self.path,
            registry=self.registry,
            service_name=self.service_name,
        )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.write_once()
            except Exception:
                _log.exception(
                    "metrics_jsonl.write_failed", extra={"path": str(self.path)}
                )
            self._stop_event.wait(self.interval_seconds)


_metrics_jsonl_writers: list[MetricsJsonlWriter] = []
_metrics_jsonl_writers_lock = threading.Lock()


def start_metrics_jsonl_writer(
    path: str | Path,
    *,
    interval_seconds: float = 5.0,
    registry: CollectorRegistry = REGISTRY,
    service_name: str | None = None,
) -> MetricsJsonlWriter:
    writer = MetricsJsonlWriter(
        path,
        interval_seconds=interval_seconds,
        registry=registry,
        service_name=service_name,
    ).start()
    with _metrics_jsonl_writers_lock:
        _metrics_jsonl_writers.append(writer)
    return writer


def _stop_metrics_jsonl_writers() -> None:
    with _metrics_jsonl_writers_lock:
        writers = list(_metrics_jsonl_writers)
        _metrics_jsonl_writers.clear()
    for writer in writers:
        writer.stop(timeout=1.0)


def _json_metric_value(value: float) -> float | str:
    number = float(value)
    if math.isfinite(number):
        return number
    if math.isnan(number):
        return "NaN"
    if number > 0:
        return "+Inf"
    return "-Inf"


def _json_exemplar(exemplar: Any) -> dict[str, Any] | None:
    if exemplar is None:
        return None
    if hasattr(exemplar, "_asdict"):
        return {
            key: value for key, value in exemplar._asdict().items() if value is not None
        }
    return {
        key: value
        for key, value in {
            "labels": getattr(exemplar, "labels", None),
            "value": getattr(exemplar, "value", None),
            "timestamp": getattr(exemplar, "timestamp", None),
        }.items()
        if value is not None
    }


atexit.register(_stop_metrics_jsonl_writers)
