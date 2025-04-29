"""Exception thrown when something doesn't exist."""


class NotFoundError(Exception):
    """
    Parent Exception for when we can't find something we expect to find.

    Allows error handlers to be defined for multiple subclasses.
    """

    def __init__(self, detail: str, *args: object) -> None:
        """
        Initialize the NotFoundError exception.

        Args:
            detail (str): The detail message for the exception.
            *args: Additional arguments for the exception.

        """
        self.detail = detail
        super().__init__(detail, *args)
