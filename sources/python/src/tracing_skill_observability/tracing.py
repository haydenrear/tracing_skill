from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, Callable, Iterator, ParamSpec, TypeVar, overload

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

DEFAULT_OTLP_ENDPOINT = "http://observability-otel-collector.observability.svc:4318"
P = ParamSpec("P")
R = TypeVar("R")


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


@overload
def traced_span(func: Callable[P, R]) -> Callable[P, R]: ...


@overload
def traced_span(
    name: str | None = None, **attributes: Any
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def traced_span(
    func: Callable[P, R] | str | None = None,
    **attributes: Any,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a function so each invocation runs inside a span.

    Use as `@traced_span`, `@traced_span()`, or
    `@traced_span("operation.name", key="value")`.
    """

    if callable(func):
        return _decorate_with_span(func, None, attributes)

    span_name = func

    def decorator(wrapped: Callable[P, R]) -> Callable[P, R]:
        return _decorate_with_span(wrapped, span_name, attributes)

    return decorator


def _decorate_with_span(
    func: Callable[P, R],
    span_name: str | None,
    attributes: dict[str, Any],
) -> Callable[P, R]:
    name = span_name or f"{func.__module__}.{func.__qualname__}"

    if iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs):
            with span(name, **attributes):
                return await func(*args, **kwargs)

        return async_wrapper

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs):
        with span(name, **attributes):
            return func(*args, **kwargs)

    return wrapper


def _trace_endpoint(otlp_endpoint: str | None) -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if explicit:
        return explicit

    base = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_OTLP_ENDPOINT
    return base if base.endswith("/v1/traces") else f"{base.rstrip('/')}/v1/traces"
