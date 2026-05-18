"""
Azure Service Bus Broker for Taskiq.

This module defines a Taskiq Azure Service Bus Broker, which provides an asynchronous
broker implementation for Azure Service Bus, along with utility functions for parsing
values and handling messaging operations.
"""

import asyncio
import gzip
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import (
    ServiceBusReceivedMessage,
    ServiceBusReceiveMode,
)
from azure.servicebus.aio import (
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusReceiver,
    ServiceBusSender,
    ServiceBusSession,
)
from azure.servicebus.amqp import AmqpAnnotatedMessage, AmqpMessageBodyType
from azure.servicebus.exceptions import MessageSizeExceededError
from pydantic import TypeAdapter
from taskiq import AckableMessage, AsyncBroker, BrokerMessage

from app.core.config import get_settings
from app.core.exceptions import MessageBrokerError, MessageTooLargeError
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import TaskPriority

_T = TypeVar("_T")

settings = get_settings()
logger = get_logger(__name__)

_COMPRESSION_THRESHOLD_BYTES = 200 * 1024


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
        priority_queue_name: str = "taskiq-priority",
    ) -> None:
        """
        Construct a new broker.

        :param connection_string: The connection string for Azure Service Bus.
            If None, the namespace parameter must be provided.
        :param namespace: The fully qualified namespace of the Service Bus.
            Used with DefaultAzureCredential if connection_string is None.
        :param queue_name: queue used to get normal priority incoming messages with.
        :param priority_queue_name: queue used to get high priority incoming
            messages with.
        """
        super().__init__()

        self.connection_string = connection_string
        self.namespace = namespace
        self._queue_name = queue_name
        self._priority_queue_name = priority_queue_name
        self.max_lock_renewal_duration = max_lock_renewal_duration

        self.service_bus_client: ServiceBusClient | None = None
        self.sender: ServiceBusSender | None = None
        self.receiver: ServiceBusReceiver | None = None
        self.priority_sender: ServiceBusSender | None = None
        self.priority_receiver: ServiceBusReceiver | None = None
        self.credential: DefaultAzureCredential | None = None
        self.auto_lock_renewer: AutoLockRenewer | None = None

        self._send_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()

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

        self.priority_sender = self.service_bus_client.get_queue_sender(
            queue_name=self._priority_queue_name
        )

        if self.is_worker_process:
            self.receiver = self.service_bus_client.get_queue_receiver(
                queue_name=self._queue_name,
                receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            )

            self.priority_receiver = self.service_bus_client.get_queue_receiver(
                queue_name=self._priority_queue_name,
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
        if self.priority_sender:
            await self.priority_sender.close()
        if self.receiver:
            await self.receiver.close()
        if self.priority_receiver:
            await self.priority_receiver.close()
        if self.service_bus_client:
            await self.service_bus_client.close()
        if self.credential:
            await self.credential.close()

    def _resolve_priority(self, message: BrokerMessage) -> TaskPriority:
        """
        Resolve the ``priority`` label on a broker message to a TaskPriority.

        Unrecognised or unparseable values log a warning and fall back to
        ``TaskPriority.NORMAL``.
        """
        raw_priority = parse_val(int, message.labels.get("priority"))
        if raw_priority is None:
            return TaskPriority.NORMAL
        try:
            return TaskPriority(raw_priority)
        except ValueError:
            logger.warning(
                "Unknown priority value, defaulting to NORMAL",
                priority=raw_priority,
                task_id=message.task_id,
            )
            return TaskPriority.NORMAL

    async def kick(self, message: BrokerMessage) -> None:
        """
        Send message to the queue.

        This function constructs a service bus message and sends it with the
        appropriate metadata and routing.

        Messages with TaskPriority.HIGH label are sent to the priority queue.

        :raises MessageBrokerError:detail= if startup wasn't called.
        :raises MessageTooLargeError:detail= if the message is too large.
        :param message: message to send.
        """
        if (
            self.sender is None
            or self.priority_sender is None
            or self.service_bus_client is None
        ):
            raise MessageBrokerError(detail="Please run startup before kicking.")

        priority = self._resolve_priority(message)
        sender = self.priority_sender if priority > TaskPriority.NORMAL else self.sender

        body = message.message
        compressed = False
        if len(body) > _COMPRESSION_THRESHOLD_BYTES:
            body = gzip.compress(body)
            compressed = True

        # Create service bus message
        service_bus_message = AmqpAnnotatedMessage(
            data_body=body,
            properties={
                "message_id": message.task_id,
                "correlation_id": message.task_id,
            },
            application_properties={
                "message_id": message.task_id,
                "renew_lock": str(message.labels.get("renew_lock", False)),
                "compressed": compressed,
            },
        )

        try:
            # Handle delay
            delay = parse_val(int, message.labels.get("delay"))
            logger.debug(
                "Sending message...",
                task_id=message.task_id,
                delay=delay,
                priority=priority,
            )

            if delay is None:
                async with self._send_lock:
                    await sender.send_messages(service_bus_message)
            else:
                # Use Azure's built-in scheduled messages feature
                scheduled_time = datetime.now(UTC) + timedelta(seconds=delay)
                async with self._send_lock:
                    await sender.schedule_messages(service_bus_message, scheduled_time)
        except MessageSizeExceededError as exc:
            raise MessageTooLargeError(detail=exc.message) from exc

    def _build_ackable(
        self,
        sb_message: ServiceBusReceivedMessage,
        receiver: ServiceBusReceiver,
    ) -> AckableMessage:
        """
        Wrap a received Service Bus message as an AckableMessage.

        Captures ``receiver`` in the ack closure so completion and lock
        renewal re-registration target the queue the message was received from.
        """
        if self.auto_lock_renewer is None:
            msg = "auto_lock_renewer must be set on the worker process"
            raise MessageBrokerError(detail=msg)

        async def ack_message(
            sb_message: ServiceBusReceivedMessage = sb_message,
            receiver: ServiceBusReceiver = receiver,
        ) -> None:
            task_id = sb_message.application_properties.get(
                b"message_id",
                sb_message.application_properties.get("message_id"),
            )
            logger.info("Attempting to complete message", task_id=task_id)
            async with self._receive_lock:
                logger.info("Completing message", task_id=task_id)
                await receiver.complete_message(sb_message)
                logger.info("Completed message", task_id=task_id)

        async def lock_renewal_failure_callback(
            sb_message: ServiceBusReceivedMessage | ServiceBusSession,
            exception: Exception | None = None,
        ) -> None:
            logger.error(
                "Lock renewal failed for message",
                task_id=sb_message.application_properties.get(
                    b"message_id",
                    sb_message.application_properties.get("message_id"),
                ),
                exception=exception,
            )
            logger.info("Attempting to re-register lock renewal")
            if self.auto_lock_renewer is not None:
                self.auto_lock_renewer.register(
                    receiver,
                    sb_message,
                    # Don't try it again if it fails
                    on_lock_renew_failure=None,
                )
                logger.info("Re-registered lock renewal")

        properties = sb_message.application_properties
        if properties and TypeAdapter(bool).validate_python(
            # Try binary then string key
            properties.get(b"renew_lock", properties.get("renew_lock", False))
        ):
            logger.info("Registering message for auto lock renewal")
            self.auto_lock_renewer.register(
                receiver,
                sb_message,
                on_lock_renew_failure=lock_renewal_failure_callback,
            )
            logger.info("Registered message for auto lock renewal")

        body_type = sb_message.body_type
        raw_body = sb_message.body

        if body_type == AmqpMessageBodyType.DATA:
            # Join all byte chunks together
            data = b"".join(raw_body)
        else:
            logger.warning(
                "Unsupported body type, defaulting to string encoding",
                body_type=body_type,
            )
            data = str(raw_body).encode("utf-8")

        if TypeAdapter(bool).validate_python(
            properties.get(b"compressed", properties.get("compressed", False))
            if properties
            else False
        ):
            data = gzip.decompress(data)

        return AckableMessage(data=data, ack=ack_message)

    async def listen(self) -> AsyncGenerator[AckableMessage, None]:
        """
        Listen on the priority queue first, then the default queue.

        Each iteration drains the priority queue with a short wait, then
        polls the default queue with a longer wait.

        If priority messages are received, re-enter priority branch to ensure
        full consumption of priority messages before moving to
        normal priority queue.

        :yields: parsed broker message.
        :raises MessageBrokerError:detail= if startup wasn't called.
        """
        if (
            self.receiver is None
            or self.priority_receiver is None
            or self.auto_lock_renewer is None
        ):
            raise MessageBrokerError(detail="Call startup before starting listening.")

        while True:
            try:
                async with self._receive_lock:
                    priority_batch = await self.priority_receiver.receive_messages(
                        max_wait_time=settings.message_broker_queue_max_wait
                    )
                for sb_message in priority_batch:
                    logger.info("Yielding priority message")
                    yield self._build_ackable(sb_message, self.priority_receiver)
                if priority_batch:
                    # Keep draining priority before touching the default queue
                    continue

                async with self._receive_lock:
                    batch_messages = await self.receiver.receive_messages(
                        max_wait_time=settings.message_broker_priority_queue_max_wait
                    )
                for sb_message in batch_messages:
                    logger.info("Yielding message")
                    yield self._build_ackable(sb_message, self.receiver)
            except Exception:
                logger.exception("Error receiving messages")
                # Wait a bit before retrying
                await asyncio.sleep(1)
