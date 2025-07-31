"""Mixes OpenTelemetry semantic conventions with application-specific attributes."""

from enum import StrEnum

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes import (
    db_attributes as _db_attributes,
)
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
from opentelemetry.semconv.attributes import (
    code_attributes,
    db_attributes,
    service_attributes,
)
from opentelemetry.util.types import AttributeValue


class Attributes(StrEnum):
    """OpenTelemetry semantic conventions for the application."""

    # Application attributes
    CODE_FUNCTION_NAME = code_attributes.CODE_FUNCTION_NAME

    # Database attributes
    DB_SYSTEM_NAME = db_attributes.DB_SYSTEM_NAME
    DB_COLLECTION_NAME = db_attributes.DB_COLLECTION_NAME
    DB_OPERATION_NAME = db_attributes.DB_OPERATION_NAME
    DB_PK = _db_attributes.DB_QUERY_PARAMETER_TEMPLATE + ".pk"
    DB_PARAMS = _db_attributes.DB_QUERY_PARAMETER_TEMPLATE

    # Deployment attributes
    DEPLOYMENT_ENVIRONMENT = _deployment_attributes.DEPLOYMENT_ENVIRONMENT

    # HTTP attributes
    HTTP_REQUEST_QUERY_PARAMS = "http.request.query"
    HTTP_REQUEST_PATH_PARAMS = "http.request.path"

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

    # Application attributes
    IMPORT_RECORD_ID = "import.record.id"
    IMPORT_BATCH_ID = "import.batch.id"

    REFERENCE_ID = "reference.id"

    SINGLE_ENHANCEMENT_REQUEST_ID = "enhancement_request.single.id"
    BATCH_ENHANCEMENT_REQUEST_ID = "enhancement_request.batch.id"


def trace_attribute(attribute: Attributes, value: AttributeValue) -> None:
    """Trace an attribute in the current span."""
    trace.get_current_span().set_attribute(attribute.value, value)
