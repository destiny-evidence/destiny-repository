"""Custom exceptions for the app."""

from typing import Any

from fastapi import HTTPException


class CustomHTTPException(HTTPException):
    """An HTTPException which is defined in our App."""


class AuthException(CustomHTTPException):
    """An exception related to HTTP authentication."""


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


class DuplicateError(Exception):
    """Exception for when we try to add something we expect to be unique."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the DuplicateError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
        super().__init__(detail, *args)


class SQLDuplicateError(DuplicateError):
    """Exception for when we try to add something we expect to be unique to the DB."""

    def __init__(
        self,
        detail: str,
        lookup_model: str,
        collision: str,
        *args: object,
    ) -> None:
        """
        Initialize the SQLDuplicateError exception.

        Args:
            detail (str): The detail message for the exception.
            lookup_model (str): The name of the model attempted to be accessed.
            collision (str): Details on the collision.
            *args: Additional arguments for the exception.

        """
        self.lookup_model = lookup_model
        self.collision = collision
        super().__init__(detail, *args)


class WrongReferenceError(Exception):
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
