"""Custom exceptions for the app."""

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
