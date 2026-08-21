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
    otel_attributes as _otel_attributes,
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
    user_agent_attributes,
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
    DB_COLLECTION_ALIAS_NAME = "db.collection.alias_name"
    DB_OPERATION_NAME = db_attributes.DB_OPERATION_NAME
    DB_PK = _db_attributes.DB_QUERY_PARAMETER_TEMPLATE + ".pk"
    DB_PARAMS = _db_attributes.DB_QUERY_PARAMETER_TEMPLATE
    DB_QUERY = db_attributes.DB_QUERY_TEXT
    DB_RECORD_COUNT = "db.record_count"

    # Deployment attributes
    DEPLOYMENT_ENVIRONMENT = _deployment_attributes.DEPLOYMENT_ENVIRONMENT

    # HTTP attributes
    HTTP_REQUEST_QUERY_PARAMS = "http.request.query"
    HTTP_REQUEST_PATH_PARAMS = "http.request.path"
    HTTP_REQUEST_BODY_PARAMS = "http.request.body"

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
    SERVICE_INSTANCE_ID = _service_attributes.SERVICE_INSTANCE_ID
    SERVICE_CONFIG = "service.config"

    # User attributes
    USER_ID = _user_attributes.USER_ID
    USER_ROLES = _user_attributes.USER_ROLES
    USER_AUTH_METHOD = "user.auth.method"
    USER_SUBJECT_TYPE = "user.subject.type"

    USER_AGENT_ORIGINAL = user_agent_attributes.USER_AGENT_ORIGINAL

    ### Application attributes

    # IDs. These must map to the camel_case version of the domain model class names.
    IMPORT_RECORD_ID = "app.import_record.id"
    IMPORT_BATCH_ID = "app.import_batch.id"
    IMPORT_RESULT_ID = "app.import_result.id"
    REFERENCE_ID = "app.reference.id"
    ENHANCEMENT_ID = "app.enhancement.id"
    ENHANCEMENT_REQUEST_ID = "app.enhancement_request.id"
    ROBOT_ENHANCEMENT_BATCH_ID = "app.robot_enhancement_batch.id"
    ROBOT_ID = "app.robot.id"
    ROBOT_AUTOMATION_ID = "app.robot_automation.id"
    REFERENCE_DUPLICATE_DECISION_ID = "app.reference_duplicate_decision.id"
    SEARCH_EXPORT_ID = "app.search_export.id"
    REFERENCE_EXPORT_ID = "app.reference_export.id"

    # Robot automation detection (percolation)
    PERCOLATION_DOCUMENT_COUNT = "app.percolation.document_count"
    PERCOLATION_MATCH_COUNT = "app.percolation.match_count"
    ROBOT_AUTOMATION_MATCH_COUNT = "app.robot_automation.match_count"
    ROBOT_AUTOMATION_PENDING_ENHANCEMENT_COUNT = (
        "app.robot_automation.pending_enhancement_count"
    )

    # Deduplication candidate retrieval
    CANDIDATE_SELECTION_RETRIEVAL_POLICY = "app.candidate_selection.retrieval_policy"
    CANDIDATE_SELECTION_K_REQUESTED = "app.candidate_selection.k_requested"
    CANDIDATE_SELECTION_INDEX_VERSION = "app.candidate_selection.index_version"
    CANDIDATE_SELECTION_SEARCHABLE = "app.candidate_selection.searchable"
    # Input presence, not policy opinion: these read the same under every policy.
    CANDIDATE_SELECTION_TITLE_PRESENT = "app.candidate_selection.title_present"
    CANDIDATE_SELECTION_AUTHORS_PRESENT = "app.candidate_selection.authors_present"
    CANDIDATE_SELECTION_PUBLICATION_YEAR_PRESENT = (
        "app.candidate_selection.publication_year_present"
    )
    CANDIDATE_SELECTION_ES_TOOK_MS = "app.candidate_selection.es_took_ms"
    CANDIDATE_SELECTION_ES_TOTAL_HITS = "app.candidate_selection.es_total_hits"
    CANDIDATE_SELECTION_ES_RETURNED = "app.candidate_selection.es_returned"
    CANDIDATE_SELECTION_IDENTIFIER_RETURNED = (
        "app.candidate_selection.identifier_returned"
    )
    # Identifier-only candidates sort ahead of ES ones, so a non-zero value means
    # rank 1 came from the identifier route.
    CANDIDATE_SELECTION_IDENTIFIER_ONLY_RETURNED = (
        "app.candidate_selection.identifier_only_returned"
    )
    CANDIDATE_SELECTION_CANDIDATE_COUNT = "app.candidate_selection.candidate_count"
    CANDIDATE_SELECTION_TRUNCATED = "app.candidate_selection.truncated"

    # Deduplication decisions
    DEDUPLICATION_ROUTE = "app.deduplication.route"
    DEDUPLICATION_DETERMINATION = "app.deduplication.determination"
    DEDUPLICATION_SIDE_EFFECT_DECISION_COUNT = (
        "app.deduplication.side_effect_decision_count"
    )
    DEDUPLICATION_DECISION_CHANGED = "app.deduplication.decision_changed"

    # The two switches deciding whether deduplication runs. Route cannot separate a
    # disabled shortcut from one that did not match this reference.
    DEDUPLICATION_CANDIDATE_SEARCH_ENABLED = (
        "app.deduplication.candidate_search_enabled"
    )
    DEDUPLICATION_TRUSTED_IDENTIFIER_SHORTCUT_ENABLED = (
        "app.deduplication.trusted_identifier_shortcut_enabled"
    )

    # Other
    FILE_LINE_NO = "app.file.line_number"


def trace_attribute(attribute: Attributes, value: AttributeValue) -> None:
    """Trace an attribute in the current span."""
    trace.get_current_span().set_attribute(attribute.value, value)


def sample_trace() -> None:
    """
    Explicitly sample the current trace.

    This ensures the span is sampled by Refinery.
    """
    trace.get_current_span().set_attribute(
        _otel_attributes.OTEL_SPAN_SAMPLING_RESULT,
        _otel_attributes.OtelSpanSamplingResultValues.RECORD_AND_SAMPLE.value,
    )


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
