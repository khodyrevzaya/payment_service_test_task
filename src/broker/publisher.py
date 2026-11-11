from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitBroker

from src.broker.topology import payments_exchange
from src.config import settings


class PaymentPublisher:
    def __init__(self) -> None:
        self.broker = RabbitBroker(settings.rabbitmq_url)

    async def start(self) -> None:
        await self.broker.start()

    async def stop(self) -> None:
        await self.broker.close()

    async def publish_payment_created(self, payment_id: str, payload: dict[str, Any]) -> None:
        await self.broker.publish(
            payload,
            exchange=payments_exchange,
            routing_key="payments.new",
        )


publisher = PaymentPublisher()