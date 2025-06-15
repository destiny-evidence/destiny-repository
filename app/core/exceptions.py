"""Custom exceptions for the app."""

import re
from typing import Any, Self

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegriyError


class CustomHTTPException(HTTPException):
    """An HTTPException which is defined in our App."""


class MessageBrokerError(Exception):
    """An exception thrown in a message broker."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the BrokerError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class NotFoundError(Exception):
    """Exception for when we can't find something we expect to find."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the NotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
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


class IntegrityError(Exception):
    """Exception for when a change would violate data integrity."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the IntegrityError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
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
    def from_sqlacademy_integrity_error(
        cls, error: SQLAlchemyIntegriyError, lookup_model: str
    ) -> Self:
        """
        Construct an SQLIntegrityError from an IntegrityError raised by SQLAlchemy.

        Attempt to parse the collision reason from the Integrity error,
        falling back to a default collision reason if not available.

        Args:
            error (sqlalchemy.exc.IntegrityError): Error thrown by sqlalchemy
            lookup_model (str): The name of the model the collision occured in.

        """
        detail = f"Unable to perform operation on {lookup_model}."

        # Try extract details from the exception message.
        # (There's no nice way to check for integrity errors before handling
        # the exception.)

        err_str = str(error)
        try:
            # Extract detail information using regex
            detail_match = re.search(r"DETAIL:\s+(.+?)(?:\n|$)", err_str)
            if detail_match:
                detail = f"Violation: {detail_match.group(1).strip()}"
                collision = detail_match.group(1).strip()

        except Exception:  # noqa: BLE001
            collision = err_str

        return cls(detail=detail, lookup_model=lookup_model, collision=collision)


class InvalidPayloadError(Exception):
    """Exception for when a payload is invalid."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the InvalidPayloadError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
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
        self.detail = detail
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
        self.detail = detail
        super().__init__(detail, *args)


class TaskError(Exception):
    """An exception thrown in a background task."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the TaskError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class SDKToDomainError(Exception):
    """
    An exeption for when we fail to convert an sdk model to a domain model.

    Exists to that we can capture a subset of pydantic validation errors.
    """

    def __init__(self, errors: list[Any]) -> None:
        """
        Initialize the SDKToDomainError exception.

        Args:
            errors (str): A sequence of errors, likely copied from ValidationError

        """
        super().__init__()
        self.errors = errors

    def __str__(self) -> str:
        """Convert exception errors to string."""
        message = f"{len(self.errors)} errors:\n"
        for error in self.errors:
            message += f"  {error}\n"
        return message


class RobotUnreachableError(Exception):
    """An exception thrown if we cannot communicate with a robot."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the RobotUnreachableError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
        super().__init__(detail, *args)


class RobotEnhancementError(Exception):
    """An exception thrown if an enhancment request cannot be processed by a robot."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the RobotEnhancementError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
        super().__init__(detail, *args)


class UOWError(Exception):
    """An exception thrown by improper use of a unit of work."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the UOWError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class BlobStorageError(Exception):
    """Base class for Blob Storage exceptions."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the BlobStorageError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class AzureError(Exception):
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
