"""
Tests for the Azure Service Bus broker implementation.

This module contains tests that verify the functionality of the AzureServiceBusBroker,
including initialization, message sending, and delayed message delivery.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid7

import pytest
from azure.servicebus.aio import (
    AutoLockRenewer,
    ServiceBusClient,
)
from azure.servicebus.amqp import AmqpAnnotatedMessage
from azure.servicebus.exceptions import MessageSizeExceededError
from taskiq import BrokerMessage
from taskiq.utils import maybe_awaitable

from app.core.azure_service_bus_broker import (
    _COMPRESSION_THRESHOLD_BYTES,
    AzureServiceBusBroker,
)
from app.core.exceptions import MessageBrokerError, MessageTooLargeError


async def get_first_task(broker: AzureServiceBusBroker):
    """
    Get first message from the queue.

    :param broker: async message broker.
    :return: first message from listen method
    """
    async for message in broker.listen():
        return message
    return None


@pytest.mark.asyncio
async def test_startup_with_connection_string():
    """
    Test broker startup with connection string.

    This test verifies that the broker initializes correctly when
    provided with a connection string.
    """
    broker = AzureServiceBusBroker(
        connection_string="Endpoint=sb://test.servicebus.windows.net/"
    )

    with patch.object(
        ServiceBusClient, "from_connection_string", return_value=MagicMock()
    ) as mock_from_conn_str:
        mock_client = mock_from_conn_str.return_value

        await broker.startup()

        mock_from_conn_str.assert_called_once_with(
            "Endpoint=sb://test.servicebus.windows.net/"
        )
        assert broker.service_bus_client is mock_client


@pytest.mark.asyncio
async def test_startup_with_namespace():
    """
    Test broker startup with namespace.

    This test verifies that the broker initializes correctly when
    provided with a namespace and uses default credentials.
    """
    broker = AzureServiceBusBroker(namespace="test-namespace.servicebus.windows.net")

    with (
        patch(
            "app.core.azure_service_bus_broker.DefaultAzureCredential",
            return_value=AsyncMock(),
        ) as mock_cred_class,
        patch(
            "app.core.azure_service_bus_broker.ServiceBusClient", autospec=True
        ) as mock_sb_client_class,
    ):
        mock_credential = mock_cred_class.return_value
        mock_sb_client = mock_sb_client_class.return_value

        await broker.startup()

        mock_sb_client_class.assert_called_once_with(
            fully_qualified_namespace="test-namespace.servicebus.windows.net",
            credential=mock_credential,
        )
        assert broker.credential is mock_credential
        assert broker.service_bus_client is mock_sb_client


@pytest.mark.asyncio
async def test_startup_without_connection_string_or_namespace_raises():
    """
    Startup raises an error when neither connection string nor namespace is provided.

    This test verifies that the broker raises a MessageBrokerError when neither
    connection_string nor namespace parameters are provided.
    """
    broker = AzureServiceBusBroker()

    with pytest.raises(
        MessageBrokerError,
        match="Either connection_string or namespace must be provided",
    ):
        await broker.startup()


@pytest.mark.anyio
async def test_happy_startup(broker: AzureServiceBusBroker) -> None:
    """
    Test that the broker initializes correctly.

    This test checks that the broker's Service Bus client,
    sender and receiver are correctly initialized.

    :param broker: Azure Service Bus broker.
    """
    assert broker.service_bus_client is not None
    assert broker.sender is not None
    assert broker.priority_sender is not None
    assert broker.receiver is not None
    assert broker.priority_receiver is not None


@pytest.mark.anyio
async def test_kick_success(
    broker: AzureServiceBusBroker,
) -> None:
    """
    Test that messages are published and read correctly.

    We kick the message and then try to listen to the queue,
    and check that message we got is the same as we sent.

    :param broker: current broker.
    """
    task_id = uuid7().hex
    task_name = uuid7().hex

    sent = BrokerMessage(
        task_id=task_id,
        task_name=task_name,
        message=b"my_msg",
        labels={
            "label1": "val1",
        },
    )

    await broker.kick(sent)

    # listen() drains the priority queue first (max_wait_time=1s) before
    # falling through to the default queue, so allow >1s for the message
    # to land here even when nothing is in priority.
    message = await asyncio.wait_for(get_first_task(broker), timeout=3.0)

    assert message.data == sent.message
    await maybe_awaitable(message.ack())

    # Check that the message has been completed after acknowledgment
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(get_first_task(broker), timeout=1.0)


@pytest.mark.anyio
async def test_delayed_message(
    broker: AzureServiceBusBroker,
) -> None:
    """
    Test that delayed messages are delivered correctly.

    This test sends a message with a delay label,
    waits for the specified delay period and
    checks that the message was delivered to the queue.

    :param broker: current broker.
    """
    broker_msg = BrokerMessage(
        task_id="delayed-task",
        task_name="delayed-name",
        message=b"delayed-message",
        labels={"delay": "2"},
    )

    # Send the delayed message
    await broker.kick(broker_msg)

    # Try to get the message immediately - should not be available yet
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(get_first_task(broker), timeout=0.1)

    # Wait for the delay to pass
    await asyncio.sleep(3)  # Wait a bit longer than the delay

    # Now the message should be available
    message = await asyncio.wait_for(get_first_task(broker), timeout=5.0)

    assert message.data == b"delayed-message"
    await maybe_awaitable(message.ack())


@pytest.mark.anyio
async def test_priority_message_routes_to_priority_sender(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Priority messages go to the priority queue, normal messages to default."""
    assert broker.sender is not None
    assert broker.priority_sender is not None
    default_sends: list[AmqpAnnotatedMessage] = []
    priority_sends: list[AmqpAnnotatedMessage] = []

    async def capture_default(message: AmqpAnnotatedMessage) -> None:
        default_sends.append(message)

    async def capture_priority(message: AmqpAnnotatedMessage) -> None:
        priority_sends.append(message)

    monkeypatch.setattr(broker.sender, "send_messages", capture_default)
    monkeypatch.setattr(broker.priority_sender, "send_messages", capture_priority)

    await broker.kick(
        BrokerMessage(
            task_id="priority-task",
            task_name="priority-name",
            message=b"priority-message",
            labels={"priority": "5"},
        )
    )
    await broker.kick(
        BrokerMessage(
            task_id="normal-task",
            task_name="normal-name",
            message=b"normal-message",
            labels={"priority": "0"},
        )
    )
    await broker.kick(
        BrokerMessage(
            task_id="no-label-task",
            task_name="no-label-name",
            message=b"no-label-message",
            labels={},
        )
    )

    assert len(priority_sends) == 1
    assert len(default_sends) == 2


@pytest.mark.anyio
async def test_unknown_priority_warns_and_falls_back_to_default(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unrecognised priority value logs a warning and routes to default."""
    assert broker.sender is not None
    assert broker.priority_sender is not None
    default_sends: list[AmqpAnnotatedMessage] = []
    priority_sends: list[AmqpAnnotatedMessage] = []

    async def capture_default(message: AmqpAnnotatedMessage) -> None:
        default_sends.append(message)

    async def capture_priority(message: AmqpAnnotatedMessage) -> None:
        priority_sends.append(message)

    monkeypatch.setattr(broker.sender, "send_messages", capture_default)
    monkeypatch.setattr(broker.priority_sender, "send_messages", capture_priority)

    with caplog.at_level("WARNING"):
        await broker.kick(
            BrokerMessage(
                task_id="unknown-priority",
                task_name="unknown-priority",
                message=b"oddball",
                labels={"priority": "99"},
            )
        )

    assert len(default_sends) == 1
    assert len(priority_sends) == 0
    assert any("Unknown priority value" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_priority_scheduled_message_routes_to_priority_sender(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delayed priority messages must also hit the priority sender."""
    assert broker.sender is not None
    assert broker.priority_sender is not None
    default_schedules: list[AmqpAnnotatedMessage] = []
    priority_schedules: list[AmqpAnnotatedMessage] = []

    async def capture_default(
        message: AmqpAnnotatedMessage,
        scheduled_time: datetime | None = None,  # noqa: ARG001
    ) -> None:
        default_schedules.append(message)

    async def capture_priority(
        message: AmqpAnnotatedMessage,
        scheduled_time: datetime | None = None,  # noqa: ARG001
    ) -> None:
        priority_schedules.append(message)

    monkeypatch.setattr(broker.sender, "schedule_messages", capture_default)
    monkeypatch.setattr(broker.priority_sender, "schedule_messages", capture_priority)

    await broker.kick(
        BrokerMessage(
            task_id="delayed-priority",
            task_name="delayed-priority",
            message=b"hi",
            labels={"priority": "5", "delay": "2"},
        )
    )
    await broker.kick(
        BrokerMessage(
            task_id="delayed-normal",
            task_name="delayed-normal",
            message=b"hi",
            labels={"delay": "2"},
        )
    )

    assert len(priority_schedules) == 1
    assert len(default_schedules) == 1


@pytest.mark.anyio
async def test_listen_drains_priority_before_default(
    broker: AzureServiceBusBroker,
) -> None:
    """Priority messages must yield before any default-queue work."""
    await broker.kick(
        BrokerMessage(
            task_id="normal-1",
            task_name="normal",
            message=b"normal-1",
            labels={},
        )
    )
    await broker.kick(
        BrokerMessage(
            task_id="normal-2",
            task_name="normal",
            message=b"normal-2",
            labels={},
        )
    )
    await broker.kick(
        BrokerMessage(
            task_id="priority-1",
            task_name="priority",
            message=b"priority-1",
            labels={"priority": "5"},
        )
    )

    yielded: list[bytes] = []
    async for ackable in broker.listen():
        yielded.append(ackable.data)
        await maybe_awaitable(ackable.ack())
        if len(yielded) == 3:
            break

    assert yielded[0] == b"priority-1"
    assert set(yielded[1:]) == {b"normal-1", b"normal-2"}


@pytest.mark.anyio
async def test_raise_custom_exception_on_oversized_message(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that messages that are too large raise a MessageTooLargeError."""

    async def mock_send_messages(message: AmqpAnnotatedMessage) -> None:  # noqa: ARG001
        raise MessageSizeExceededError(message="message size limit exceeded")

    monkeypatch.setattr(broker.sender, "send_messages", mock_send_messages)

    with pytest.raises(MessageTooLargeError, match="size limit exceeded"):
        await broker.kick(
            BrokerMessage(
                task_id=uuid7().hex,
                task_name=uuid7().hex,
                message=b"A big message we definitely cannot possibly process this",
                labels={
                    "label1": "val1",
                },
            )
        )


@pytest.mark.anyio
async def test_large_message_is_compressed_and_decompressed(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that messages over 200KB are compressed and decompressed."""
    assert broker.sender is not None
    sent_message = None

    original_send_messages = broker.sender.send_messages

    async def capture_send_messages(message: AmqpAnnotatedMessage) -> None:
        nonlocal sent_message
        sent_message = message
        await original_send_messages(message)

    monkeypatch.setattr(broker.sender, "send_messages", capture_send_messages)

    original_body = b"x" * (_COMPRESSION_THRESHOLD_BYTES + 1)

    await broker.kick(
        BrokerMessage(
            task_id="large-task",
            task_name="large-name",
            message=original_body,
            labels={},
        )
    )

    # Confirm the wire body is compressed (smaller than original) and flagged
    assert isinstance(sent_message, AmqpAnnotatedMessage)
    assert sent_message.application_properties.get("compressed") is True
    wire_body = b"".join(sent_message.body)
    assert len(wire_body) < len(original_body)

    # Confirm the received data is transparently decompressed back to the original
    message = await asyncio.wait_for(get_first_task(broker), timeout=3.0)
    assert message.data == original_body
    await maybe_awaitable(message.ack())


@pytest.mark.anyio
async def test_small_message_is_not_compressed(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that messages at or below 200KB are sent without compression."""
    assert broker.sender is not None
    sent_message = None

    original_send_messages = broker.sender.send_messages

    async def capture_send_messages(message: AmqpAnnotatedMessage) -> None:
        nonlocal sent_message
        sent_message = message
        await original_send_messages(message)

    monkeypatch.setattr(broker.sender, "send_messages", capture_send_messages)

    small_body = b"small"
    await broker.kick(
        BrokerMessage(
            task_id="small-task",
            task_name="small-name",
            message=small_body,
            labels={},
        )
    )

    assert isinstance(sent_message, AmqpAnnotatedMessage)
    assert sent_message.application_properties.get("compressed") is False
    message = await asyncio.wait_for(get_first_task(broker), timeout=3.0)
    assert message.data == small_body
    await maybe_awaitable(message.ack())


@pytest.mark.anyio
@pytest.mark.parametrize("renew_lock", [True, False, None])
async def test_only_renew_lock_when_specified(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
    *,
    renew_lock: bool,
) -> None:
    """
    Test that message lock is renewed only when specified.

    This test sends a message with and without the renew_lock label,
    and checks that the lock renewal behavior is as expected.

    :param broker: current broker.
    """
    mock_lock_renewer = AsyncMock(spec=AutoLockRenewer)
    monkeypatch.setattr(broker, "auto_lock_renewer", mock_lock_renewer)

    msg = BrokerMessage(
        task_id="task-id",
        task_name="task-name",
        message=b"task-message",
        labels={"label": "foo"},
    )
    if renew_lock is not None:
        msg.labels["renew_lock"] = renew_lock

    await broker.kick(msg)
    await asyncio.wait_for(get_first_task(broker), timeout=3.0)
    if renew_lock:
        mock_lock_renewer.register.assert_called_once()
    else:
        mock_lock_renewer.register.assert_not_called()
