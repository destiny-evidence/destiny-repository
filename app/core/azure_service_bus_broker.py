"""
Azure Service Bus Broker for Taskiq.

This module defines a Taskiq Azure Service Bus Broker, which provides an asynchronous
broker implementation for Azure Service Bus, along with utility functions for parsing
values and handling messaging operations.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import ServiceBusReceivedMessage, ServiceBusReceiveMode
from azure.servicebus.aio import (
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusReceiver,
    ServiceBusSender,
)
from azure.servicebus.amqp import AmqpAnnotatedMessage, AmqpMessageBodyType
from structlog import get_logger
from taskiq import AckableMessage, AsyncBroker, BrokerMessage

from app.core.config import get_settings
from app.core.exceptions import MessageBrokerError

_T = TypeVar("_T")

settings = get_settings()
logger = get_logger(__name__)


def parse_val(
    parse_func: Callable[[str], _T],
    target: str | None = None,
) -> _T | None:
    """
    Parse string to some value.

    :param parse_func: function to use if value is present.
    :param target: value to parse, defaults to None
    :return: Optional value.
    """
    if target is None:
        return None

    try:
        return parse_func(target)
    except ValueError:
        return None


class AzureServiceBusBroker(AsyncBroker):
    """
    Broker that works with Azure Service Bus.

    See https://taskiq-python.github.io/extending-taskiq/broker.html
    """

    def __init__(
        self,
        max_lock_renewal_duration: int = 10800,  # 3 hours
        connection_string: str | None = None,
        namespace: str | None = None,
        queue_name: str = "taskiq",
    ) -> None:
        """
        Construct a new broker.

        :param connection_string: The connection string for Azure Service Bus.
            If None, the namespace parameter must be provided.
        :param namespace: The fully qualified namespace of the Service Bus.
            Used with DefaultAzureCredential if connection_string is None.
        :param queue_name: queue that used to get incoming messages.
        :param connection_kwargs: additional keyword arguments.
        """
        super().__init__()

        self.connection_string = connection_string
        self.namespace = namespace
        self._queue_name = queue_name
        self.max_lock_renewal_duration = max_lock_renewal_duration

        self.service_bus_client: ServiceBusClient | None = None
        self.sender: ServiceBusSender | None = None
        self.receiver: ServiceBusReceiver | None = None
        self.credential: DefaultAzureCredential | None = None
        self.auto_lock_renewer: AutoLockRenewer | None = None

    async def startup(self) -> None:
        """Initialize connections and create queues if needed."""
        await super().startup()

        if self.connection_string is not None:
            self.service_bus_client = ServiceBusClient.from_connection_string(
                self.connection_string,
            )
        elif self.namespace is not None:
            self.credential = DefaultAzureCredential()
            self.service_bus_client = ServiceBusClient(
                fully_qualified_namespace=self.namespace,
                credential=self.credential,
            )
        else:
            raise MessageBrokerError(
                detail="Either connection_string or namespace must be provided"
            )

        self.sender = self.service_bus_client.get_queue_sender(
            queue_name=self._queue_name
        )

        if self.is_worker_process:
            self.receiver = self.service_bus_client.get_queue_receiver(
                queue_name=self._queue_name,
                receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            )
            if not self.auto_lock_renewer:
                self.auto_lock_renewer = AutoLockRenewer(
                    max_lock_renewal_duration=self.max_lock_renewal_duration
                )

    async def shutdown(self) -> None:
        """Close all connections on shutdown."""
        await super().shutdown()

        if self.sender:
            await self.sender.close()
        if self.receiver:
            await self.receiver.close()
        if self.service_bus_client:
            await self.service_bus_client.close()
        if self.credential:
            await self.credential.close()

    async def kick(self, message: BrokerMessage) -> None:
        """
        Send message to the queue.

        This function constructs a service bus message and sends it with the
        appropriate metadata and routing.

        :raises MessageBrokerError:detail= if startup wasn't called.
        :param message: message to send.
        """
        if self.sender is None or self.service_bus_client is None:
            raise MessageBrokerError(detail="Please run startup before kicking.")

        headers = {}
        priority = parse_val(int, message.labels.get("priority"))
        if priority is not None:
            headers["priority"] = priority

        # Create service bus message
        service_bus_message = AmqpAnnotatedMessage(
            data_body=message.message,
            header=headers,
            properties={
                "message_id": message.task_id,
                "correlation_id": message.task_id,
            },
        )

        # Handle delay
        delay = parse_val(int, message.labels.get("delay"))

        logger.debug(
            "Sending message...", extra={"task_id": message.task_id, "delay": delay}
        )

        if delay is None:
            # Send message directly to main queue
            await self.sender.send_messages(service_bus_message)
        else:
            # Use Azure's built-in scheduled messages feature
            scheduled_time = datetime.now(UTC) + timedelta(seconds=delay)
            await self.sender.schedule_messages(service_bus_message, scheduled_time)

    async def listen(self) -> AsyncGenerator[AckableMessage, None]:
        """
        Listen to queue.

        This function listens to the queue and yields every new message.

        :yields: parsed broker message.
        :raises MessageBrokerError:detail= if startup wasn't called.
        """
        if self.receiver is None or self.auto_lock_renewer is None:
            raise MessageBrokerError(detail="Call startup before starting listening.")

        while True:
            try:
                # Receive a batch of messages
                batch_messages = await self.receiver.receive_messages()

                # Process each message
                for sb_message in batch_messages:
                    self.auto_lock_renewer.register(self.receiver, sb_message)

                    async def ack_message(
                        sb_message: ServiceBusReceivedMessage = sb_message,
                    ) -> None:
                        if self.receiver is not None:
                            await self.receiver.complete_message(sb_message)
                        else:
                            logger.error(
                                "Receiver is None. Cannot complete the message."
                            )

                    body_type = sb_message.body_type
                    raw_body = sb_message.body

                    if body_type == AmqpMessageBodyType.DATA:
                        # Join all byte chunks together
                        data = b"".join(raw_body)
                    else:
                        logger.warning(
                            "Unsupported body type, defaulting to string encoding",
                            extra={body_type: body_type},
                        )
                        data = str(raw_body).encode("utf-8")

                    ackable = AckableMessage(
                        data=data,
                        ack=ack_message,
                    )

                    yield ackable
            except Exception:
                logger.exception("Error receiving messages")
                # Wait a bit before retrying
                await asyncio.sleep(1)
