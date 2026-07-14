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
    log_mode: str | None = None
    logs_endpoint: str | None = None
    metrics_enabled: bool = True
    metrics_port: int | None = None
    metrics_addr: str = "0.0.0.0"
    metrics_export_interval_seconds: float = 15.0


def load_config(path: str | Path) -> ObservabilityConfig:
    payload = tomllib.loads(Path(path).read_text())
    data = payload.get("observability", payload)
    return ObservabilityConfig(
        service_name=data.get("service_name"),
        service_version=data.get("service_version"),
        otlp_endpoint=data.get("otlp_endpoint"),
        log_level=data.get("log_level", "INFO"),
        log_mode=data.get("log_mode"),
        logs_endpoint=data.get("logs_endpoint"),
        metrics_enabled=data.get("metrics_enabled", True),
        metrics_port=data.get("metrics_port"),
        metrics_addr=data.get("metrics_addr", "0.0.0.0"),
        metrics_export_interval_seconds=data.get(
            "metrics_export_interval_seconds", 15.0
        ),
    )


def configure_observability_from_file(path: str | Path) -> None:
    from . import configure_observability

    config = load_config(path)
    configure_observability(
        service_name=config.service_name,
        service_version=config.service_version,
        otlp_endpoint=config.otlp_endpoint,
        log_level=config.log_level,
        log_mode=config.log_mode,
        logs_endpoint=config.logs_endpoint,
        metrics_enabled=config.metrics_enabled,
        metrics_port=config.metrics_port,
        metrics_addr=config.metrics_addr,
        metrics_export_interval_seconds=config.metrics_export_interval_seconds,
    )
