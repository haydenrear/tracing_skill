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
    metrics_port: int | None = None


def load_config(path: str | Path) -> ObservabilityConfig:
    payload = tomllib.loads(Path(path).read_text())
    data = payload.get("observability", payload)
    return ObservabilityConfig(
        service_name=data.get("service_name"),
        service_version=data.get("service_version"),
        otlp_endpoint=data.get("otlp_endpoint"),
        log_level=data.get("log_level", "INFO"),
        metrics_port=data.get("metrics_port"),
    )


def configure_observability_from_file(path: str | Path) -> None:
    from . import configure_observability

    config = load_config(path)
    configure_observability(
        service_name=config.service_name,
        service_version=config.service_version,
        otlp_endpoint=config.otlp_endpoint,
        log_level=config.log_level,
        metrics_port=config.metrics_port,
    )
