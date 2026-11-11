from __future__ import annotations

from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue, ExchangeType

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

# Main queue with DLX and delivery limit
# - x-dead-letter-exchange / x-dead-letter-routing-key: route to DLQ on rejection or expiry
# - x-delivery-limit: RabbitMQ enforces max 3 deliveries; protects against infinite
#   redelivery if the consumer crashes before calling RejectMessage()
payments_new_queue = RabbitQueue(
    "payments.new",
    durable=True,
    arguments={
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.dlq",
        "x-delivery-limit": 3,
    },
)

# Dead Letter Queue
payments_dlq = RabbitQueue(
    "payments.dlq",
    durable=True,
)


async def declare_topology(broker: RabbitBroker) -> None:
    """Declare DLX exchange, DLQ, and bind them together."""
    await broker.declare_exchange(payments_dlx)
    await broker.declare_queue(payments_dlq)
    # Bind DLQ to DLX — use aio_pika's queue.bind() via the underlying channel.
    # RobustChannel has declare_queue() which returns an aio_pika Queue with .bind().
    channel = broker._channel  # type: ignore[union-attr]
    dlq = await channel.declare_queue(
        payments_dlq.name,
        durable=True,
    )
    await dlq.bind(payments_dlx.name, routing_key="payments.dlq")