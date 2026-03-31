"""Unit tests for AsyncUnitOfWorkBase."""

from unittest.mock import MagicMock

import pytest
from opentelemetry import trace

from app.core.exceptions import SQLNotFoundError
from app.persistence.uow import AsyncUnitOfWorkBase


class ConcreteUoW(AsyncUnitOfWorkBase):
    async def rollback(self) -> None:
        pass

    async def commit(self) -> None:
        pass


@pytest.fixture
def uow():
    instance = ConcreteUoW()
    instance._is_active = True  # noqa: SLF001
    return instance


async def test_not_found_error_logs_warning_not_exception(uow, monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("app.persistence.uow.logger", mock_logger)

    exc = SQLNotFoundError(
        detail="not found",
        lookup_model="Foo",
        lookup_type="id",
        lookup_value="123",
    )
    await uow.__aexit__(type(exc), exc, None)

    mock_logger.warning.assert_called_once()
    mock_logger.exception.assert_not_called()


async def test_not_found_error_does_not_set_error_span_status(uow, monkeypatch):
    monkeypatch.setattr("app.persistence.uow.logger", MagicMock())
    mock_set_span_status = MagicMock()
    monkeypatch.setattr("app.persistence.uow.set_span_status", mock_set_span_status)

    exc = SQLNotFoundError(
        detail="not found",
        lookup_model="Foo",
        lookup_type="id",
        lookup_value="123",
    )
    await uow.__aexit__(type(exc), exc, None)

    mock_set_span_status.assert_not_called()


async def test_unexpected_error_logs_exception_and_sets_error_span_status(
    uow, monkeypatch
):
    mock_logger = MagicMock()
    monkeypatch.setattr("app.persistence.uow.logger", mock_logger)
    mock_set_span_status = MagicMock()
    monkeypatch.setattr("app.persistence.uow.set_span_status", mock_set_span_status)

    exc = RuntimeError("something unexpected")
    await uow.__aexit__(type(exc), exc, None)

    mock_logger.exception.assert_called_once()
    mock_logger.warning.assert_not_called()
    mock_set_span_status.assert_called_once_with(trace.StatusCode.ERROR, str(exc), exc)
