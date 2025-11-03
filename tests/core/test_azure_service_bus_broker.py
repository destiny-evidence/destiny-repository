"""
Tests for the Azure Service Bus broker implementation.

This module contains tests that verify the functionality of the AzureServiceBusBroker,
including initialization, message sending, and delayed message delivery.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.amqp import AmqpAnnotatedMessage
from taskiq import BrokerMessage
from taskiq.utils import maybe_awaitable

from app.core.azure_service_bus_broker import AzureServiceBusBroker
from app.core.exceptions import MessageBrokerError


async def get_first_task(broker: AzureServiceBusBroker):
    """
    Get first message from the queue.

    :param broker: async message broker.
    :return: first message from listen method
    """
    async for message in broker.listen():  # noqa: RET503
        return message


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
    assert broker.receiver is not None


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
    task_id = uuid.uuid4().hex
    task_name = uuid.uuid4().hex

    sent = BrokerMessage(
        task_id=task_id,
        task_name=task_name,
        message=b"my_msg",
        labels={
            "label1": "val1",
        },
    )

    await broker.kick(sent)

    message = await asyncio.wait_for(get_first_task(broker), timeout=1.0)

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
async def test_priority_handling(
    broker: AzureServiceBusBroker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test that priority is correctly set in the message headers.

    :param broker: current broker.
    :param test_sender: test sender.
    :param test_receiver: test receiver.
    """
    assert broker.sender is not None
    original_send_messages = broker.sender.send_messages
    sent_message = None

    async def mock_send_messages(message: AmqpAnnotatedMessage) -> None:
        nonlocal sent_message
        sent_message = message
        await original_send_messages(message)

    monkeypatch.setattr(broker.sender, "send_messages", mock_send_messages)
    await broker.kick(
        BrokerMessage(
            task_id="priority-task",
            task_name="priority-name",
            message=b"priority-message",
            labels={"priority": "5"},
        )
    )

    assert isinstance(sent_message, AmqpAnnotatedMessage)
    assert sent_message.header is not None
    assert sent_message.header.priority == 5


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
    mock_lock_renewer = AsyncMock()
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
    await asyncio.wait_for(get_first_task(broker), timeout=1.0)
    if renew_lock:
        mock_lock_renewer.register.assert_called_once()
    else:
        mock_lock_renewer.register.assert_not_called()
