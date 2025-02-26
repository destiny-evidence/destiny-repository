"""Custom exceptions for the app."""

from fastapi import HTTPException


class CustomHTTPException(HTTPException):
    """An HTTPException which is defined in our App."""
