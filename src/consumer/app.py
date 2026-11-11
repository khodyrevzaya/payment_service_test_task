from __future__ import annotations

import logging

from faststream import FastStream
from faststream.rabbit import RabbitBroker

from src.broker.topology import declare_topology, payments_exchange, payments_new_queue
from src.config import settings
from src.consumer.handler import handle_payment_created

logger = logging.getLogger(__name__)

broker = RabbitBroker(settings.rabbitmq_url)
app = FastStream(broker)


@broker.subscriber(payments_new_queue, exchange=payments_exchange)
async def on_payment_created(payload: dict) -> None:
    """Handle payment.created event from queue."""
    payment_id = payload.get("payment_id")
    if not payment_id:
        logger.error("Missing payment_id in message", extra={"payload": payload})
        return

    await handle_payment_created(payment_id)


@app.after_startup
async def setup_topology() -> None:
    """Declare exchanges and queues on startup."""
    await declare_topology(broker)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Consumer starting")
    await app.run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())