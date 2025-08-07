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

    ### OTEL attributes (with a few extensions)

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
    MESSAGING_RETRIES_REMAINING = "messaging.retries_remaining"

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

    ### Application attributes

    # IDs. These must map to the camel_case version of the domain model class names.
    IMPORT_RECORD_ID = "app.import_record.id"
    IMPORT_BATCH_ID = "app.import_batch.id"
    IMPORT_RESULT_ID = "app.import_result.id"
    REFERENCE_ID = "app.reference.id"
    ENHANCEMENT_ID = "app.enhancement.id"
    ENHANCEMENT_REQUEST_ID = "app.enhancement_request.id"
    BATCH_ENHANCEMENT_REQUEST_ID = "app.batch_enhancement_request.id"
    ROBOT_ID = "app.robot.id"
    ROBOT_AUTOMATION_ID = "app.robot_automation.id"

    # Other
    FILE_LINE_NO = "app.file.line_number"


def trace_attribute(attribute: Attributes, value: AttributeValue) -> None:
    """Trace an attribute in the current span."""
    trace.get_current_span().set_attribute(attribute.value, value)


def name_span(name: str) -> None:
    """Set the name of the current span."""
    trace.get_current_span().update_name(name)


def set_span_status(
    status: trace.StatusCode,
    detail: str | None = None,
    exception: BaseException | None = None,
) -> None:
    """Set the status of the current span."""
    trace.get_current_span().set_status(trace.Status(status, detail))
    if exception:
        trace.get_current_span().record_exception(exception)
