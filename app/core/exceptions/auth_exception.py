"""Exceptions related to authentication."""

from app.core.exceptions.custom_exception import CustomHTTPException


class AuthException(CustomHTTPException):
    """An exception related to HTTP authentication."""
