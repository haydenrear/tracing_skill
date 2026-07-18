from __future__ import annotations

import os

from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)


def create_observability_resource(
    service_name: str | None,
    service_version: str | None,
) -> Resource:
    """Resolve one OpenTelemetry resource identity for every signal."""

    attributes: dict[str, str] = {}
    service = service_name or os.getenv("OTEL_SERVICE_NAME")
    if service:
        attributes[SERVICE_NAME] = service
    if service_version:
        attributes[SERVICE_VERSION] = service_version
    deployment_environment = os.getenv("DEPLOYMENT_ENVIRONMENT")
    if deployment_environment:
        attributes[DEPLOYMENT_ENVIRONMENT] = deployment_environment
    return Resource.create(attributes)


def observability_service_name(resource: Resource) -> str | None:
    """Return the service identity selected by an OpenTelemetry resource."""

    service_name = resource.attributes.get(SERVICE_NAME)
    return str(service_name) if service_name is not None else None
