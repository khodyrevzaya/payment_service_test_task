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

# Main queue with DLX (retry is handled in consumer handler, not via x-delivery-limit)
payments_new_queue = RabbitQueue(
    "payments.new",
    durable=True,
    arguments={
        "x-queue-type": "quorum",
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