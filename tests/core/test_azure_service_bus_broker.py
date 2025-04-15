"""
Tests for the Azure Service Bus broker implementation.

This module contains tests that verify the functionality of the AzureServiceBusBroker,
including initialization, message sending, and delayed message delivery.
"""

import asyncio
import uuid

import pytest
from azure.servicebus.amqp import AmqpAnnotatedMessage
from taskiq import BrokerMessage
from taskiq.utils import maybe_awaitable

from app.core.azure_service_bus_broker import AzureServiceBusBroker


async def get_first_task(broker: AzureServiceBusBroker):
    """
    Get first message from the queue.

    :param broker: async message broker.
    :return: first message from listen method
    """
    async for message in broker.listen():  # noqa: RET503
        return message


@pytest.mark.anyio
async def test_startup(broker: AzureServiceBusBroker) -> None:
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

    # Allow time for the message to be processed
    message = await asyncio.wait_for(get_first_task(broker), timeout=1.0)

    assert message.data == sent.message
    await maybe_awaitable(message.ack())


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
    # Use monkey patching to capture the message
    original_send_messages = broker.sender.send_messages
    sent_message = None

    # Use monkeypatch to replace the send_messages method
    async def mock_send_messages(message: AmqpAnnotatedMessage) -> None:
        nonlocal sent_message
        sent_message = message
        await original_send_messages(message)

    monkeypatch.setattr(broker.sender, "send_messages", mock_send_messages)
    # Send a message with priority
    await broker.kick(
        BrokerMessage(
            task_id="priority-task",
            task_name="priority-name",
            message=b"priority-message",
            labels={"priority": "5"},
        )
    )

    # Check that the priority was set in the message headers
    assert isinstance(sent_message, AmqpAnnotatedMessage)
    assert sent_message.header is not None
    assert sent_message.header.priority == 5
