from .config import ObservabilityConfig, configure_observability_from_file, load_config
from .logging import JsonLogFormatter, configure_logging, get_logger
from .metrics import (
    PrometheusOtlpPusher,
    http_requests_total,
    http_request_duration,
    metrics_app,
    start_metrics_otlp_pusher,
    start_metrics_server,
    trace_metric_labels,
)
from .tracing import configure_tracing, get_tracer, span, traced_span


def configure_observability(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
    log_level: str = "INFO",
    log_mode: str | None = None,
    logs_endpoint: str | None = None,
    metrics_enabled: bool = True,
    metrics_port: int | None = None,
    metrics_addr: str = "0.0.0.0",
    metrics_export_interval_seconds: float = 15.0,
) -> None:
    configure_logging(
        service_name=service_name,
        service_version=service_version,
        log_level=log_level,
        log_mode=log_mode,
        logs_endpoint=logs_endpoint,
        otlp_endpoint=otlp_endpoint,
    )
    configure_tracing(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
    )
    if metrics_enabled:
        start_metrics_otlp_pusher(
            interval_seconds=metrics_export_interval_seconds,
            service_name=service_name,
            service_version=service_version,
            otlp_endpoint=otlp_endpoint,
        )
        if metrics_port is not None:
            start_metrics_server(metrics_port, addr=metrics_addr)


__all__ = [
    "JsonLogFormatter",
    "ObservabilityConfig",
    "PrometheusOtlpPusher",
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
    "start_metrics_otlp_pusher",
    "start_metrics_server",
    "trace_metric_labels",
    "traced_span",
]
