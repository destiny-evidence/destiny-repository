"""Mixes OpenTelemetry semantic conventions with application-specific attributes."""

from enum import StrEnum

from opentelemetry.semconv._incubating.attributes import (
    deployment_attributes as _deployment_attributes,
)
from opentelemetry.semconv._incubating.attributes import (
    messaging_attributes as _messaging_attributes,
)
from opentelemetry.semconv._incubating.attributes import (
    service_attributes as _service_attributes,
)
from opentelemetry.semconv._incubating.attributes import (
    user_attributes as _user_attributes,
)
from opentelemetry.semconv.attributes import service_attributes


class SemConv(StrEnum):
    """OpenTelemetry semantic conventions for the application."""

    # Deployment attributes
    DEPLOYMENT_ENVIRONMENT = _deployment_attributes.DEPLOYMENT_ENVIRONMENT

    # Messaging attributes
    MESSAGING_SYSTEM = _messaging_attributes.MESSAGING_SYSTEM
    MESSAGING_DESTINATION_NAME = _messaging_attributes.MESSAGING_DESTINATION_NAME
    MESSAGING_OPERATION = _messaging_attributes.MESSAGING_OPERATION
    MESSAGING_MESSAGE_ID = _messaging_attributes.MESSAGING_MESSAGE_ID

    # Service attributes
    SERVICE_NAME = service_attributes.SERVICE_NAME
    SERVICE_VERSION = service_attributes.SERVICE_VERSION
    SERVICE_NAMESPACE = _service_attributes.SERVICE_NAMESPACE

    # User attributes
    USER_ID = _user_attributes.USER_ID
    USER_EMAIL = _user_attributes.USER_EMAIL
    USER_FULL_NAME = _user_attributes.USER_FULL_NAME
    USER_ROLES = _user_attributes.USER_ROLES
    USER_AUTH_METHOD = "user.auth.method"
