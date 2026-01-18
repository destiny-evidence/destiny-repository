"""
Pydantic models and adapters used to validate reference data.

A validator differs from an anti-corruption service in that it returns
information about the parsing process as well as the converted data.
"""

import html
import json
import re
from dataclasses import dataclass
from typing import Self
from urllib.parse import unquote
from uuid import UUID

import destiny_sdk
from destiny_sdk.enhancements import EnhancementType
from pydantic import UUID4, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.core.exceptions import ParseError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    ExternalIdentifier,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    IdentifierLookup,
    Visibility,
)
from app.utils.types import JSON

logger = get_logger(__name__)


# =============================================================================
# DOI Cleanup Utilities
# =============================================================================


@dataclass
class DOICleanupResult:
    """Result of DOI cleanup attempt."""

    original: str
    cleaned: str
    was_modified: bool
    actions: list[str]


# Pattern to extract DOI from text (10.XXXX/... format)
# Note: DOIs can contain <> characters (SICI-style DOIs) so we only exclude \s and "
_DOI_PATTERN = re.compile(r"10\.[0-9]{4,9}/[^\s\"]+", re.IGNORECASE)

# Common DOI URL prefixes to strip
_DOI_PREFIXES = (
    "doi:",
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)

# DOI prefixes that are unsafe for deduplication (cause mass collisions)
# - 10.13039: Crossref Funder Registry DOIs (assigned to funders, not papers)
_UNSAFE_DOI_PREFIXES = ("10.13039/",)

# Pattern for invalid percent escapes (not valid %XX hex)
# Valid: %2F, %3A, etc. Invalid: %x, %s, %%, %X (single char)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def is_doi_safe_for_dedup(doi: str) -> tuple[bool, str | None]:
    """
    Check if a DOI is safe to use for deduplication.

    Expects an already-cleaned DOI. Caller is responsible for cleaning.
    Returns (True, None) if safe, (False, reason) if unsafe.

    Unsafe DOIs include:
    - Funder DOIs (10.13039/*): Assigned to funding organizations, not papers.
      Many papers incorrectly have these as their DOI, causing mass collisions.
    - Template DOIs (with invalid percent escapes like %x, %s): Unresolved
      placeholder DOIs from broken publishing systems.

    Note: Valid percent-encoded DOIs (e.g., 10.1234/test%2Fslash) are allowed.
    Only invalid escapes (not %XX hex) indicate template placeholders.
    """
    # Check for funder DOIs
    for prefix in _UNSAFE_DOI_PREFIXES:
        if doi.startswith(prefix):
            return False, f"funder_doi:{prefix}"

    # Check for invalid percent escapes (template placeholders like %x, %s)
    if _INVALID_PERCENT_ESCAPE.search(doi):
        return False, "template_doi"

    return True, None


def clean_doi(doi: str) -> DOICleanupResult:  # noqa: PLR0912, PLR0915
    """
    Clean a DOI by removing URL cruft (prefixes, query params, encoding, etc.).

    Handles common DOI formats:
    - doi:10.1234/abc
    - https://doi.org/10.1234/abc
    - 10.1234/abc?utm_source=...
    - 10.1234%2Fabc (percent-encoded)
    - 10.1234/abc#section (fragments)
    - 10.1234/abc). (trailing punctuation)

    IMPORTANT: Fragment/query stripping happens BEFORE URL-decoding to prevent
    encoded characters (%3F, %23) from being decoded and then stripped.
    """
    actions: list[str] = []
    cleaned = doi.strip()

    # Unescape HTML entities first
    if "&" in cleaned:
        unescaped = html.unescape(cleaned)
        if unescaped != cleaned:
            actions.append("unescape_html")
            cleaned = unescaped

    # Strip DOI URL prefixes (doi:, https://doi.org/, etc.)
    lower = cleaned.lower()
    for prefix in _DOI_PREFIXES:
        if lower.startswith(prefix):
            actions.append("strip_prefix")
            cleaned = cleaned[len(prefix) :].lstrip()
            lower = cleaned.lower()
            break

    # Strip fragment (#section) - BEFORE URL-decoding to preserve %23
    if "#" in cleaned:
        actions.append("strip_fragment")
        cleaned = cleaned.split("#", 1)[0]

    # Strip query parameters - BEFORE URL-decoding to preserve %3F
    if "?" in cleaned:
        actions.append("strip_query_params")
        cleaned = cleaned.split("?", 1)[0]

    # Strip session IDs (case-insensitive)
    parts = re.split(r";jsessionid=", cleaned, flags=re.IGNORECASE, maxsplit=1)
    if len(parts) > 1:
        actions.append("strip_jsessionid")
        cleaned = parts[0]

    # URL-decode percent-encoded characters - AFTER stripping query/fragment
    decoded = unquote(cleaned)
    if decoded != cleaned:
        actions.append("url_decode")
        cleaned = decoded

    # Strip tracking garbage
    for pattern, action_name in [
        ("&magic=", "magic"),
        ("&prog=", "prog"),
        ("&utm", "utm"),
    ]:
        if pattern in cleaned:
            actions.append(f"strip_{action_name}")
            cleaned = cleaned.split(pattern)[0]

    # Strip URL path suffixes
    for suffix in ["/abstract", "/full", "/pdf", "/epdf", "/summary"]:
        if cleaned.endswith(suffix):
            actions.append(f"strip_{suffix[1:]}")
            cleaned = cleaned[: -len(suffix)]

    # Strip trailing HTML tags (from malformed source data)
    # e.g., "10.1234/abc</p" or "10.1234/abc</div>\n</div>"
    html_tag_match = re.search(r"</\w+.*$", cleaned)
    if html_tag_match:
        actions.append("strip_html_tags")
        cleaned = cleaned[: html_tag_match.start()]

    # Strip trailing punctuation (common from copy/paste)
    # But preserve balanced parentheses - only strip ) if unbalanced
    original_len = len(cleaned)
    # First strip obviously trailing punct that's never valid in DOIs
    cleaned = cleaned.rstrip(".,;]\"'")
    # Single-pass parentheses balancing (avoid O(n²) repeated .count() calls)
    open_count = cleaned.count("(")
    close_count = cleaned.count(")")
    excess_close = close_count - open_count
    while excess_close > 0 and cleaned.endswith(")"):
        cleaned = cleaned[:-1]
        excess_close -= 1
    if len(cleaned) < original_len:
        actions.append("strip_trailing_punct")

    cleaned = cleaned.strip()

    # If there's extra text around the DOI, try to extract just the DOI
    match = _DOI_PATTERN.search(cleaned)
    if match and match.group(0) != cleaned:
        actions.append("extract_doi")
        cleaned = match.group(0)

    return DOICleanupResult(
        original=doi,
        cleaned=cleaned,
        was_modified=cleaned != doi,
        actions=actions,
    )


# =============================================================================
# Validators
# =============================================================================


class ReferenceFileInputValidator(BaseModel):
    """Validator for the top-level schema of a reference entry from a file."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[JSON] = Field(min_length=1)
    enhancements: list[JSON] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ExternalIdentifierParseResult(BaseModel):
    """Result of an attempt to parse an external identifier."""

    external_identifier: ExternalIdentifier | None = Field(
        default=None,
        description="The external identifier to create",
        discriminator="identifier_type",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the parsing process",
    )

    @classmethod
    def from_raw(cls, raw_identifier: JSON, entry_ref: int) -> Self:
        """
        Parse an external identifier from raw JSON.

        For DOI identifiers, applies cleanup (removing URL cruft, query params, etc.)
        and safety checks (rejecting funder DOIs and template DOIs that cause mass
        collisions during deduplication).
        """
        try:
            # Preprocess DOIs before SDK validation
            if (
                isinstance(raw_identifier, dict)
                and raw_identifier.get("identifier_type") == "doi"
            ):
                raw_identifier = cls._preprocess_doi(raw_identifier, entry_ref)
                if raw_identifier is None:
                    # DOI was unsafe (funder/template) - skip this identifier
                    return cls(error=f"Identifier {entry_ref}: Skipped (unsafe DOI)")

            identifier: ExternalIdentifier = ExternalIdentifierAdapter.validate_python(
                raw_identifier
            )
            return cls(external_identifier=identifier)
        except (TypeError, ValueError) as error:
            return cls(
                error=f"""
Identifier {entry_ref}:
Invalid identifier. Check the format and content of the identifier.
Attempted to parse:
{raw_identifier}
Error:
{error}
"""
            )
        except Exception as error:
            logger.exception(
                "Failed to create identifier",
                raw_identifier=raw_identifier,
                line_no=entry_ref,
            )
            return cls(
                error=f"""
Identifier {entry_ref}:
Failed to create identifier.
Attempted to parse:
{raw_identifier}
Error:
{error}
"""
            )

    @classmethod
    def _preprocess_doi(  # noqa: PLR0911
        cls, raw_identifier: dict, entry_ref: int
    ) -> dict | None:
        """
        Clean and validate a DOI identifier before SDK parsing.

        Uses a repair-on-failure approach:
        1. Try SDK validation first - don't clean already-valid DOIs
        2. If valid, check safety only
        3. If invalid, try cleaning and retry validation
        4. Only apply transforms if original fails AND cleaned passes

        Returns the (possibly cleaned) identifier dict, or None if the DOI should
        be skipped (unsafe funder/template DOIs).
        """
        raw_doi = raw_identifier.get("identifier")

        # Type guard: let SDK validation handle non-string identifiers
        if not isinstance(raw_doi, str) or not raw_doi:
            return raw_identifier

        # Try validation first - don't clean already-valid DOIs
        original_valid = False
        try:
            ExternalIdentifierAdapter.validate_python(raw_identifier)
            original_valid = True
        except (TypeError, ValueError):
            pass  # Validation failed, try cleaning

        if original_valid:
            # Already valid - just check safety
            is_safe, reason = is_doi_safe_for_dedup(raw_doi)
            if not is_safe:
                logger.info(
                    "Skipping unsafe DOI on import",
                    doi=raw_doi[:256],
                    reason=reason,
                    entry_ref=entry_ref,
                )
                return None
            return raw_identifier

        # Clean and retry validation
        cleanup = clean_doi(raw_doi)
        if not cleanup.was_modified:
            return raw_identifier  # Nothing to clean, let validation fail normally

        cleaned_identifier = {**raw_identifier, "identifier": cleanup.cleaned}
        cleaned_valid = False
        try:
            ExternalIdentifierAdapter.validate_python(cleaned_identifier)
            cleaned_valid = True
        except (TypeError, ValueError):
            pass  # Cleaning didn't help

        if not cleaned_valid:
            return raw_identifier  # Let validation fail normally

        # Cleaned version valid - check safety and use it
        is_safe, reason = is_doi_safe_for_dedup(cleanup.cleaned)
        if not is_safe:
            logger.info(
                "Skipping unsafe DOI on import",
                doi=raw_doi[:256],
                reason=reason,
                entry_ref=entry_ref,
            )
            return None
        logger.debug(
            "Cleaned DOI on import",
            original=raw_doi[:256],
            cleaned=cleanup.cleaned,
            actions=cleanup.actions,
            entry_ref=entry_ref,
        )
        return cleaned_identifier


class EnhancementParseResult(BaseModel):
    """Result of an attempt to parse an enhancement."""

    enhancement: destiny_sdk.enhancements.EnhancementFileInput | None = Field(
        default=None,
        description="The enhancement to create",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the parsing process",
    )

    @classmethod
    def from_raw(cls, raw_enhancement: JSON, entry_ref: int) -> Self:
        """Parse an enhancement from raw JSON."""
        try:
            enhancement = destiny_sdk.enhancements.EnhancementFileInput.model_validate(
                raw_enhancement
            )
            return cls(enhancement=enhancement)
        except (TypeError, ValueError) as error:
            return cls(
                error=f"""
Enhancement {entry_ref}:
Invalid enhancement. Check the format and content of the enhancement.
Error:
{error}
"""
            )
        except Exception as error:
            logger.exception(
                "Failed to create enhancement",
                raw_enhancement=raw_enhancement,
                line_no=entry_ref,
            )
            return cls(
                error=f"""
Enhancement {entry_ref}:
Failed to create enhancement.
Error:
{error}
"""
            )


class ReferenceCreateResult(BaseModel):
    """
    Result of an attempt to create a reference.

    If reference is None, no reference was created and errors will be populated.
    If reference exists and there are errors, the reference was created but there
    were errors in the hydration.
    If reference exists and there are no errors, the reference was created and all
    enhancements/identifiers were hydrated successfully from the input.
    If duplicate_decision_id is set, the reference is pending deduplication.
    """

    reference: destiny_sdk.references.ReferenceFileInput | None = Field(
        default=None,
        description="The validated reference input.",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="A list of errors encountered during the creation process",
    )
    reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the created reference, if created",
    )
    duplicate_decision_id: UUID4 | None = Field(
        default=None,
        description="The ID of the pending duplicate decision, if required",
    )

    @property
    def error_str(self) -> str | None:
        """Return a string of errors if they exist."""
        return "\n\n".join(e.strip() for e in self.errors) if self.errors else None

    @classmethod
    def from_raw(
        cls,
        record_str: str,
        entry_ref: int,
    ) -> Self:
        """Parse a reference file input from a string and validate it."""
        try:
            raw_reference: dict = json.loads(record_str)
            # Validate top-level JSON schema using Pydantic
            validated_input = ReferenceFileInputValidator.model_validate(raw_reference)
        except (json.JSONDecodeError, ValidationError) as exc:
            return cls(errors=[f"Entry {entry_ref}:", str(exc)])

        identifier_results: list[ExternalIdentifierParseResult] = [
            ExternalIdentifierParseResult.from_raw(identifier, entry_ref)
            for entry_ref, identifier in enumerate(validated_input.identifiers, 1)
        ]

        # Fail out if all identifiers failed
        identifier_errors = [
            result.error for result in identifier_results if result.error
        ]
        if len(identifier_errors) == len(identifier_results):
            return cls(
                errors=[
                    f"Entry {entry_ref:}",
                    "   All identifiers failed to parse.",
                    *identifier_errors,
                ]
            )

        enhancement_results: list[EnhancementParseResult] = [
            EnhancementParseResult.from_raw(enhancement, entry_ref)
            for entry_ref, enhancement in enumerate(validated_input.enhancements, 1)
        ]

        errors = [
            result.error
            for result in identifier_results + enhancement_results
            if result.error
        ]

        return cls(
            reference=destiny_sdk.references.ReferenceFileInput(
                visibility=raw_reference.get(  # type: ignore[union-attr]
                    "visibility",
                    destiny_sdk.references.ReferenceFileInput.model_fields[
                        "visibility"
                    ].get_default(),
                ),
                identifiers=[
                    result.external_identifier
                    for result in identifier_results
                    if result.external_identifier
                ],
                enhancements=[
                    result.enhancement
                    for result in enhancement_results
                    if result.enhancement
                ],
            ),
            errors=[f"Entry ref {entry_ref}:", *errors] if errors else [],
        )


class EnhancementResultValidator(BaseModel):
    """Result of a batch enhancement request."""

    enhancement_to_add: destiny_sdk.enhancements.Enhancement | None = Field(
        default=None,
        description="An enhancement to add to the references",
    )
    robot_error: destiny_sdk.robots.LinkedRobotError | None = Field(
        default=None,
        description="An error encountered by the robot during processing",
    )
    parse_failure: str | None = Field(
        default=None,
        description=("An error encountered while parsing the batch enhancement result"),
    )

    @classmethod
    def from_raw(
        cls,
        entry: str,
        entry_ref: int,
        expected_reference_ids: set[UUID],
        processed_reference_ids: set[UUID] | None = None,
    ) -> Self:
        """Create a EnhancementResult from a jsonl entry."""
        file_entry_validator: TypeAdapter[destiny_sdk.robots.EnhancementResultEntry] = (
            TypeAdapter(destiny_sdk.robots.EnhancementResultEntry)
        )

        try:
            file_entry = file_entry_validator.validate_json(entry)
        except ValidationError as exception:
            return cls(
                parse_failure=f"Entry {entry_ref} could not be parsed: {exception}."
            )

        if file_entry.reference_id not in expected_reference_ids:
            return cls(
                robot_error=destiny_sdk.robots.LinkedRobotError(
                    reference_id=file_entry.reference_id,
                    message="Reference not in batch enhancement request.",
                )
            )

        # Check for duplicate reference IDs if tracking is enabled
        if (
            processed_reference_ids is not None
            and file_entry.reference_id in processed_reference_ids
        ):
            return cls(
                robot_error=destiny_sdk.robots.LinkedRobotError(
                    reference_id=file_entry.reference_id,
                    message="Duplicate reference ID in enhancement result.",
                )
            )

        if isinstance(file_entry, destiny_sdk.enhancements.Enhancement):
            # Do not allow raw enhancements to be created by robots
            if file_entry.content.enhancement_type == EnhancementType.RAW:
                return cls(
                    robot_error=destiny_sdk.robots.LinkedRobotError(
                        reference_id=file_entry.reference_id,
                        message="Robot returned illegal raw enhancement type",
                    )
                )

            return cls(
                enhancement_to_add=file_entry,
            )
        return cls(robot_error=file_entry)


def parse_identifier_lookup_from_string(
    identifier_lookup_string: str,
    delimiter: str = ":",
) -> IdentifierLookup:
    """Parse an identifier lookup string into an IdentifierLookup object."""
    if delimiter not in identifier_lookup_string:
        try:
            UUID4(identifier_lookup_string)
        except ValueError as exc:
            msg = (
                f"Invalid identifier lookup string: {identifier_lookup_string}. "
                "Must be UUIDv4 if no identifier type is specified."
            )
            raise ParseError(msg) from exc
        return IdentifierLookup(
            identifier=identifier_lookup_string,
            identifier_type=None,
        )
    identifier_type, identifier = identifier_lookup_string.split(delimiter, 1)
    if identifier_type == ExternalIdentifierType.OTHER:
        if delimiter not in identifier:
            msg = (
                f"Invalid identifier lookup string: {identifier_lookup_string}. "
                "Other identifier type must include other identifier name."
            )
            raise ParseError(msg)
        other_identifier_type, identifier = identifier.split(delimiter, 1)
        return IdentifierLookup(
            identifier=identifier,
            identifier_type=ExternalIdentifierType.OTHER,
            other_identifier_name=other_identifier_type,
        )
    if identifier_type not in ExternalIdentifierType:
        msg = (
            f"Invalid identifier lookup string: {identifier_lookup_string}. "
            f"Unknown identifier type: {identifier_type}."
        )
        raise ParseError(msg)
    return IdentifierLookup(
        identifier=identifier,
        identifier_type=ExternalIdentifierType(identifier_type),
    )
