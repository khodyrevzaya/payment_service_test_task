from __future__ import annotations

import asyncio
import logging

from datetime import datetime, timezone

from sqlalchemy import select

from src.broker.publisher import publisher
from src.broker.topology import declare_topology, payments_exchange
from src.db.base import async_session_factory
from src.db.enums import OutboxStatus
from src.db.models import OutboxEvent

logger = logging.getLogger(__name__)

MAX_OUTBOX_ATTEMPTS = 3


async def process_outbox() -> None:
    """Main outbox relay loop: poll pending events and publish to RabbitMQ."""
    logger.info("Outbox relay started")

    await publisher.start()
    await declare_topology(publisher.broker)

    try:
        while True:
            try:
                async with async_session_factory() as session:
                    # Select pending events with FOR UPDATE SKIP LOCKED
                    result = await session.execute(
                        select(OutboxEvent)
                        .where(OutboxEvent.status == OutboxStatus.pending)
                        .order_by(OutboxEvent.created_at)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                    events = result.scalars().all()

                    if events:
                        for event in events:
                            try:
                                await publisher.broker.publish(
                                    event.payload,
                                    exchange=payments_exchange,
                                    routing_key="payments.new",
                                )
                                event.status = OutboxStatus.published
                                event.published_at = datetime.now(timezone.utc)
                                logger.info("Published outbox event", extra={"event_id": str(event.id), "payment_id": str(event.aggregate_id)})
                            except Exception as e:
                                event.attempts += 1
                                if event.attempts >= MAX_OUTBOX_ATTEMPTS:
                                    event.status = OutboxStatus.dead
                                    logger.error(
                                        "Outbox event exhausted all attempts, marked as dead",
                                        extra={"event_id": str(event.id), "attempts": event.attempts, "error": str(e)},
                                    )
                                else:
                                    logger.error("Failed to publish outbox event", extra={"event_id": str(event.id), "error": str(e)})

                        await session.commit()
                    else:
                        await session.rollback()

            except Exception as e:
                logger.error("Outbox relay error", extra={"error": str(e)})

            await asyncio.sleep(2)
    finally:
        await publisher.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(process_outbox())