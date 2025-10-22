"""Custom exceptions for the app."""

import re
from typing import Any, Self

import destiny_sdk
from fastapi import HTTPException
from opentelemetry.trace import StatusCode
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from app.core.telemetry.attributes import set_span_status


class CustomHTTPException(HTTPException):
    """An HTTPException which is defined in our App."""


class DestinyRepositoryError(Exception):
    """Base class for all exceptions in the Destiny Repository app."""

    def __init__(self, detail: str | None = None, *args: object) -> None:
        """
        Initialize the DestinyRepositoryException.

        Args:
            *args: Additional arguments for the exception.
            **kwargs: Additional keyword arguments for the exception.

        """
        set_span_status(
            StatusCode.ERROR,
            detail=detail,
            exception=self,
        )
        self.detail = detail or "No detail provided."
        super().__init__(detail, *args)


class MessageBrokerError(DestinyRepositoryError):
    """An exception thrown in a message broker."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the BrokerError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class NotFoundError(DestinyRepositoryError):
    """Exception for when we can't find something we expect to find."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the NotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class SQLNotFoundError(NotFoundError):
    """Exception for when we can't find something in the database."""

    def __init__(
        self,
        detail: str,
        lookup_model: str,
        lookup_type: str,
        lookup_value: object,
        *args: object,
    ) -> None:
        """
        Initialize the SQLNotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            lookup_model (str): The name of the model attempted to be accessed.
            lookup_type (str): The type of lookup performed (e.g., "id", "name").
            lookup_value (Any): The value(s) used in the lookup.
            *args: Additional arguments for the exception.

        """
        self.lookup_model = lookup_model
        self.lookup_type = lookup_type
        self.lookup_value = lookup_value
        super().__init__(detail, *args)


class SQLValueError(DestinyRepositoryError):
    """Exception for when a value is invalid for a SQL operation."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the SQLValueError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class IntegrityError(DestinyRepositoryError):
    """Exception for when a change would violate data integrity."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the IntegrityError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class SQLIntegrityError(IntegrityError):
    """Exception for when a change would violate data integrity in the database."""

    def __init__(
        self,
        detail: str,
        lookup_model: str,
        collision: str,
        *args: object,
    ) -> None:
        """
        Initialize the SQLIntegrityError exception.

        Args:
            detail (str): The detail message for the exception.
            lookup_model (str): The name of the model attempted to be accessed.
            collision (str): Details on the integrity violation.
            *args: Additional arguments for the exception.

        """
        self.lookup_model = lookup_model
        self.collision = collision
        super().__init__(detail, *args)

    @classmethod
    def from_sqlalchemy_integrity_error(
        cls, error: SQLAlchemyIntegrityError, lookup_model: str
    ) -> Self:
        """
        Construct an SQLIntegrityError from an IntegrityError raised by SQLAlchemy.

        Attempt to parse the collision reason from the Integrity error,
        falling back to a default collision reason if not available.

        Args:
            error (sqlalchemy.exc.IntegrityError): Error thrown by sqlalchemy
            lookup_model (str): The name of the model the collision occured in.

        """
        # Try extract details from the exception message.
        # (There's no nice way to check for integrity errors before handling
        # the exception.)

        err_str = str(error)
        try:
            # Extract detail information using regex
            reason_match = re.search(r"DETAIL:\s+(.+?)(?:\n|$)", err_str)
            if reason_match:
                collision = f"Violation: {reason_match.group(1).strip()}"

        except Exception:  # noqa: BLE001
            collision = err_str

        return cls(
            detail=f"Unable to perform operation on {lookup_model}.",
            lookup_model=lookup_model,
            collision=collision,
        )


class ESError(DestinyRepositoryError):
    """An exception thrown in an Elasticsearch operation."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the ESError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class InvalidPayloadError(DestinyRepositoryError):
    """Exception for when a payload is invalid."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the InvalidPayloadError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class ESNotFoundError(NotFoundError, ESError):
    """Exception for when we can't find something in Elasticsearch."""

    def __init__(
        self,
        detail: str,
        lookup_model: str,
        lookup_type: str,
        lookup_value: object,
        *args: object,
    ) -> None:
        """
        Initialize the SQLNotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            lookup_model (str): The name of the model attempted to be accessed.
            lookup_type (str): The type of lookup performed (e.g., "id", "name").
            lookup_value (Any): The value(s) used in the lookup.
            *args: Additional arguments for the exception.

        """
        self.lookup_model = lookup_model
        self.lookup_type = lookup_type
        self.lookup_value = lookup_value
        super().__init__(detail, *args)


class ESMalformedDocumentError(ESError):
    """Exception for when an Elasticsearch document is malformed."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the ESMalformedDocumentError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class WrongReferenceError(InvalidPayloadError):
    """Exception for when enhancement is for a different reference than requested."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the NotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class InvalidParentEnhancementError(InvalidPayloadError):
    """Exception for when a derived enhancement references an invalid enhancement."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the InvalidParentEnhancementError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class TaskError(DestinyRepositoryError):
    """An exception thrown in a background task."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the TaskError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class SDKTranslationError(DestinyRepositoryError):
    """
    An exception thrown when we fail to translate a SDK model.

    Exists so that we can capture a subset of pydantic validation errors.
    """

    def __init__(self, errors: list[Any]) -> None:
        """
        Initialize the SDKTranslationError exception.

        Args:
            errors (str): A sequence of errors, likely copied from ValidationError

        """
        self.errors = errors
        super().__init__(str(self))

    def __str__(self) -> str:
        """Convert pydantic exception errors to string."""
        message = f"{len(self.errors)} errors:\n"
        for error in self.errors:
            message += f"  {error}\n"
        return message


class SDKToDomainError(SDKTranslationError):
    """An exception for when we fail to convert a sdk model to a domain model."""


class DomainToSDKError(SDKTranslationError):
    """An exception for when we fail to convert a domain model to a sdk model."""


class RobotUnreachableError(DestinyRepositoryError):
    """An exception thrown if we cannot communicate with a robot."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the RobotUnreachableError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class RobotEnhancementError(DestinyRepositoryError):
    """An exception thrown if an enhancment request cannot be processed by a robot."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the RobotEnhancementError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class UOWError(DestinyRepositoryError):
    """An exception thrown by improper use of a unit of work."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the UOWError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class BlobStorageError(DestinyRepositoryError):
    """Base class for Blob Storage exceptions."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the BlobStorageError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class AzureError(DestinyRepositoryError):
    """Base class for Azure exceptions."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the AzureError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class AzureBlobStorageError(BlobStorageError, AzureError):
    """Exception for Azure Blob Storage errors."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the AzureBlobStorageError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class MinioBlobStorageError(BlobStorageError):
    """Exception for MinIO Blob Storage errors."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the MinioBlobStorageError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class AuthError(destiny_sdk.auth.AuthException):
    """An exception thrown by the authentication system."""

    def __init__(
        self,
        status_code: int,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize the AuthError exception.

        Args:
            *args: Additional arguments for the exception.

        """
        super().__init__(status_code, detail, headers)
        set_span_status(
            StatusCode.ERROR,
            detail=detail,
            exception=self,
        )


class SQLPreloadError(DestinyRepositoryError):
    """An exception thrown when requesting a relationship that hasn't been preloaded."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the SQLPreloadError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class ProjectionError(DestinyRepositoryError):
    """An exception for when we fail to project a domain model."""

    def __init__(self, detail: str) -> None:
        """
        Initialize the ProjectionError exception.

        Args:
            detail (str): The detail message for the exception.

        """
        super().__init__(detail)


class DeduplicationError(DestinyRepositoryError):
    """An exception for when something goes wrong in deduplication."""

    def __init__(self, detail: str) -> None:
        """
        Initialize the DeduplicationError exception.

        Args:
            detail (str): The detail message for the exception.

        """
        super().__init__(detail)


class DeduplicationValueError(DeduplicationError, ValueError):
    """An exception for when a value provided to deduplication is invalid."""

    def __init__(self, detail: str) -> None:
        """
        Initialize the DeduplicationValueError exception.

        Args:
            detail (str): The detail message for the exception.

        """
        super().__init__(detail)


class DuplicateEnhancementError(DestinyRepositoryError):
    """An exception for when an exact duplicate enhancement is detected."""

    def __init__(self, detail: str) -> None:
        """
        Initialize the DuplicateEnhancementError exception.

        Args:
            detail (str): The detail message for the exception.

        """
        super().__init__(detail)
