from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, REGISTRY, make_asgi_app, start_http_server

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
