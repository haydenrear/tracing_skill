from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObservabilityConfig:
    service_name: str | None = None
    service_version: str | None = None
    otlp_endpoint: str | None = None
    log_level: str = "INFO"
    metrics_enabled: bool = True
    metrics_port: int | None = None
    metrics_addr: str = "0.0.0.0"
    metrics_jsonl_path: str | None = None
    metrics_jsonl_interval_seconds: float = 5.0


def load_config(path: str | Path) -> ObservabilityConfig:
    payload = tomllib.loads(Path(path).read_text())
    data = payload.get("observability", payload)
    return ObservabilityConfig(
        service_name=data.get("service_name"),
        service_version=data.get("service_version"),
        otlp_endpoint=data.get("otlp_endpoint"),
        log_level=data.get("log_level", "INFO"),
        metrics_enabled=data.get("metrics_enabled", True),
        metrics_port=data.get("metrics_port"),
        metrics_addr=data.get("metrics_addr", "0.0.0.0"),
        metrics_jsonl_path=data.get("metrics_jsonl_path"),
        metrics_jsonl_interval_seconds=data.get("metrics_jsonl_interval_seconds", 5.0),
    )


def configure_observability_from_file(path: str | Path) -> None:
    from . import configure_observability

    config = load_config(path)
    configure_observability(
        service_name=config.service_name,
        service_version=config.service_version,
        otlp_endpoint=config.otlp_endpoint,
        log_level=config.log_level,
        metrics_port=config.metrics_port if config.metrics_enabled else None,
        metrics_addr=config.metrics_addr,
        metrics_jsonl_path=config.metrics_jsonl_path if config.metrics_enabled else None,
        metrics_jsonl_interval_seconds=config.metrics_jsonl_interval_seconds,
    )
