from .config import ObservabilityConfig, configure_observability_from_file, load_config
from .logging import JsonLogFormatter, configure_logging, get_logger
from .metrics import (
    http_requests_total,
    http_request_duration,
    metrics_app,
    start_metrics_server,
)
from .tracing import configure_tracing, get_tracer, span, traced_span


def configure_observability(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
    log_level: str = "INFO",
    metrics_port: int | None = None,
    metrics_addr: str = "0.0.0.0",
) -> None:
    configure_logging(service_name=service_name, log_level=log_level)
    configure_tracing(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
    )
    if metrics_port is not None:
        start_metrics_server(metrics_port, addr=metrics_addr)


__all__ = [
    "JsonLogFormatter",
    "ObservabilityConfig",
    "configure_logging",
    "configure_observability",
    "configure_observability_from_file",
    "configure_tracing",
    "get_logger",
    "get_tracer",
    "http_request_duration",
    "http_requests_total",
    "load_config",
    "metrics_app",
    "span",
    "start_metrics_server",
    "traced_span",
]
