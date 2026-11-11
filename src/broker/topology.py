from __future__ import annotations

from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue, ExchangeType

from src.config import settings

# Exchange
payments_exchange = RabbitExchange(
    "payments",
    type=ExchangeType.DIRECT,
    durable=True,
)

# Dead Letter Exchange
payments_dlx = RabbitExchange(
    "payments.dlx",
    type=ExchangeType.DIRECT,
    durable=True,
)

# Main queue with DLX + retry limit (quorum queue for x-delivery-limit support)
payments_new_queue = RabbitQueue(
    "payments.new",
    durable=True,
    arguments={
        "x-queue-type": "quorum",
        "x-delivery-limit": 3,
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.dlq",
    },
)

# Dead Letter Queue
payments_dlq = RabbitQueue(
    "payments.dlq",
    durable=True,
)


async def declare_topology(broker: RabbitBroker) -> None:
    """Declare DLX exchange and DLQ (main queue is created by subscriber)."""
    await broker.declare_exchange(payments_dlx)
    await broker.declare_queue(payments_dlq)