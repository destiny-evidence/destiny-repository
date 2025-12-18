"""Custom exceptions for destiny sdk parsers."""


class ExternalIdentifierNotFoundError(Exception):
    """Raised when an reference has no identifiable external identifiers."""

    def __init__(self, detail: str | None = None, *args: object) -> None:
        """
        Initialize the ExternalIdentifiersNotFoundError.

        Args:
            *args: Additional arguments for the exception.
            **kwargs: Additional keyword arguments for the exception.

        """
        self.detail = detail or "No detail provided."
        super().__init__(detail, *args)
