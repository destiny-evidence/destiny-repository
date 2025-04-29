"""Exceptions thrown in the references domain."""

from app.core.exceptions.not_found_exception import NotFoundError


class ReferenceNotFoundError(NotFoundError):
    """Exception for when a reference does not exist."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the ReferenceNotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)


class RobotNotFoundError(NotFoundError):
    """Exception for when a robot does not exist."""

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the RobotNotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        super().__init__(detail, *args)
