# Python Prometheus Export

Use this reference when Python services need a standardized Prometheus
metrics endpoint.

## Install

```bash
tracing-observability-install --project /path/to/project
```

## ASGI Applications

For FastAPI, Starlette, or other ASGI apps, mount the shared metrics app
at `/metrics`:

```python
from fastapi import FastAPI
from tracing_skill_observability import configure_observability, metrics_app

app = FastAPI()
configure_observability(service_name="orders-api", service_version="0.1.0")
app.mount("/metrics", metrics_app())
```

The service should expose a named container port for Prometheus scraping.
Use the platform chart’s ServiceMonitor conventions for the exact port
name and path.

## Non-ASGI Processes

For workers or scripts that do not already run an HTTP server, start a
standalone metrics exporter:

```python
from tracing_skill_observability import configure_observability

configure_observability(service_name="orders-worker", metrics_port=9464)
```

Equivalent TOML config:

```toml
[observability]
service_name = "orders-worker"
service_version = "0.1.0"
metrics_port = 9464
```

## Standard HTTP Metrics

The package exposes a counter and histogram for HTTP request metrics:

```python
from tracing_skill_observability import http_request_duration, http_requests_total

route = "/orders/{id}"
status = "200"

http_requests_total.labels(method="GET", route=route, status=status).inc()
with http_request_duration.labels(method="GET", route=route, status=status).time():
    handle_request()
```

Labels should be low-cardinality. Use route templates such as
`/orders/{id}`, not raw request paths like `/orders/ord_123`.

## Library Guidance

Reusable libraries should define domain-specific metrics only when the
metric is part of the library’s public operational contract. Application
code should own HTTP route labels, service names, and exporter setup.
