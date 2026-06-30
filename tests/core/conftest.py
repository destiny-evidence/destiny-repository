"""Test setup for core modules."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from azure.servicebus import ServiceBusReceiveMode
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.amqp import AmqpAnnotatedMessage

from app.core.azure_service_bus_broker import AzureServiceBusBroker
from app.core.config import get_settings

settings = get_settings()


class FakeServiceBusSender:
    """
    Fake Service Bus sender for testing.

    Each instance is bound to a queue (via the FakeServiceBusClient that
    created it) and writes into that queue's pending-task list, so tests
    can assert which queue a message was routed to.
    """

    def __init__(self, pending_tasks: list[asyncio.Task[AmqpAnnotatedMessage]]) -> None:
        """Bind the sender to its queue's pending-task list."""
        self._pending_tasks = pending_tasks

    async def schedule_messages(
        self, message: AmqpAnnotatedMessage, scheduled_time: datetime | None = None
    ) -> None:
        """
        Simulate sending messages asynchronously with a scheduled time.

        :param message: The message to be sent.
        :param scheduled_time: Optional scheduled time for the message.
        """
        if not scheduled_time:
            scheduled_time = datetime.now(UTC) + timedelta(seconds=0.1)

        delay = (scheduled_time - datetime.now(UTC)).total_seconds()

        async def _delayed_append() -> AmqpAnnotatedMessage:
            await asyncio.sleep(delay)
            return message

        task = asyncio.create_task(_delayed_append())
        self._pending_tasks.append(task)

    async def send_messages(
        self,
        message: AmqpAnnotatedMessage,
    ) -> None:
        """
        Simulate sending messages asynchronously.

        :param message: The message to be sent.
        """
        scheduled_time = datetime.now(UTC) + timedelta(seconds=0.1)
        await self.schedule_messages(message, scheduled_time)

    async def close(self) -> None:
        """Simulate closing the sender."""


class FakeServiceBusReceiver:
    """
    Fake Service Bus receiver for testing.

    Reads from a per-queue pending-task list so the priority queue and the
    default queue are observable independently.
    """

    def __init__(self, pending_tasks: list[asyncio.Task[AmqpAnnotatedMessage]]) -> None:
        """Bind the receiver to its queue's pending-task list."""
        self._pending_tasks = pending_tasks

    async def receive_messages(
        self,
        max_wait_time: float | None = None,
    ) -> list:
        """
        Simulate receiving messages asynchronously.

        :param max_message_count: Maximum number of messages to receive.
        :param max_wait_time: Maximum time to wait for messages.
        :return: List of received messages.
        """
        deadline = asyncio.get_event_loop().time() + (max_wait_time or 60)

        while True:
            results = [t.result() for t in self._pending_tasks if t.done()]

            if results:
                return results

            # Timeout reached, return empty
            if asyncio.get_event_loop().time() > deadline:
                return []

            # Sleep a bit before checking again
            await asyncio.sleep(0.01)

    async def complete_message(self, message: AmqpAnnotatedMessage) -> None:
        """Simulate completing a message."""
        for task in self._pending_tasks:
            if task.done() and task.result() == message:
                self._pending_tasks.remove(task)

    async def close(self) -> None:
        """Simulate closing the receiver."""


class FakeServiceBusClient:
    """
    Fake Service Bus client for testing.

    Keeps a separate pending-task list per queue so default/priority queue
    routing can be verified.
    """

    def __init__(self) -> None:
        """Create an empty registry of per-queue pending-task lists."""
        self.queues: dict[str, list[asyncio.Task[AmqpAnnotatedMessage]]] = {}

    def _get_queue(self, queue_name: str) -> list[asyncio.Task[AmqpAnnotatedMessage]]:
        return self.queues.setdefault(queue_name, [])

    def get_queue_sender(self, queue_name: str) -> FakeServiceBusSender:
        """Get ServiceBusSender for the specific queue."""
        return FakeServiceBusSender(self._get_queue(queue_name))

    def get_queue_receiver(
        self,
        queue_name: str,
        receive_mode: ServiceBusReceiveMode,  # noqa: ARG002
    ) -> FakeServiceBusReceiver:
        """Get ServiceBusReceiver for the specific queue."""
        return FakeServiceBusReceiver(self._get_queue(queue_name))

    async def close(self) -> None:
        """Close the client."""


class FakeServiceBusAutoLockRenewer:
    """
    Fake Service Bus AutoLockRenewer for testing.

    This class is used to mock the behavior of the actual
    Azure Service Bus AutoLockRenewer during unit tests.
    """

    async def register(
        self, receiver: FakeServiceBusReceiver, message: AmqpAnnotatedMessage
    ) -> None:
        """Simulate registering a message for lock renewal."""

    async def close(self) -> None:
        """Simulate closing the auto lock renewer."""


@pytest.fixture
def queue_name() -> str:
    """
    Get test queue name.

    :return: test queue name.
    """
    return "taskiq-test-queue"


@pytest.fixture
def priority_queue_name() -> str:
    """
    Get test priority queue name.

    :return: test priority queue name.
    """
    return "taskiq-test-queue-priority"


@pytest.fixture
def connection_string() -> str | None:
    """
    Get custom Azure Service Bus connection string.

    This function tries to get custom connection string,
    or returns None otherwise.

    :return: Azure Service Bus connection string.
    """
    return settings.message_broker_url


@pytest.fixture
async def broker(
    connection_string: str,
    queue_name: str,
    priority_queue_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AzureServiceBusBroker, None]:
    """
    Yield a new broker instance.

    This function is used to create broker,
    run startup, and shutdown after test.

    :param connection_string: connection string for Azure Service Bus.
    :param queue_name: test queue name.
    :param priority_queue_name: test priority queue name.
    :yield: broker.
    """
    broker = AzureServiceBusBroker(
        connection_string=connection_string,
        queue_name=queue_name,
        priority_queue_name=priority_queue_name,
    )
    broker.auto_lock_renewer = FakeServiceBusAutoLockRenewer()
    broker.is_worker_process = True

    monkeypatch.setattr(
        ServiceBusClient,
        "from_connection_string",
        lambda *_args, **_kwargs: FakeServiceBusClient(),
    )
    await broker.startup()

    yield broker

    await broker.shutdown()
