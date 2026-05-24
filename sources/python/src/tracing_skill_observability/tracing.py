from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

DEFAULT_OTLP_ENDPOINT = "http://observability-otel-collector.observability.svc:4318"


def configure_tracing(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
) -> None:
    endpoint = _trace_endpoint(otlp_endpoint)
    attributes: dict[str, str] = {}

    service = service_name or os.getenv("OTEL_SERVICE_NAME")
    if service:
        attributes[SERVICE_NAME] = service
    if service_version:
        attributes[SERVICE_VERSION] = service_version
    if os.getenv("DEPLOYMENT_ENVIRONMENT"):
        attributes[DEPLOYMENT_ENVIRONMENT] = os.environ["DEPLOYMENT_ENVIRONMENT"]

    resource = Resource.create(attributes)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def get_tracer(name: str | None = None) -> trace.Tracer:
    return trace.get_tracer(name or os.getenv("OTEL_SERVICE_NAME") or "tracing-skill")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with get_tracer().start_as_current_span(name) as active_span:
        for key, value in attributes.items():
            active_span.set_attribute(key, value)
        yield active_span


def _trace_endpoint(otlp_endpoint: str | None) -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if explicit:
        return explicit

    base = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_OTLP_ENDPOINT
    return base if base.endswith("/v1/traces") else f"{base.rstrip('/')}/v1/traces"
