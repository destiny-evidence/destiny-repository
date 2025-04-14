"""Exceptions thrown in the message broker."""


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
