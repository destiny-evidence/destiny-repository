"""Structured logging wrapper class."""

import structlog


class Logger:
    """Structured logging wrapper class."""

    def __init__(self) -> None:
        """Initialize the logger with the specified logger name."""
        self.logger = structlog.get_logger()

    def debug(self, message: str, **kwargs: dict) -> None:
        """Log a message with level DEBUG."""
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: dict) -> None:
        """Log a message with level INFO."""
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: dict) -> None:
        """Log a message with level WARNING."""
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: dict) -> None:
        """Log a message with level ERROR."""
        self.logger.error(message, **kwargs)

    def exception(self, message: str, **kwargs: dict) -> None:
        """
        Log a message with level ERROR.

        Exception info is added to the logging message.
        """
        self.logger.exception(message, **kwargs)


def get_logger() -> Logger:
    """Return a structured logger."""
    return Logger()
