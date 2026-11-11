from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import OutboxStatus, PaymentStatus
from src.db.models import OutboxEvent, Payment
from src.services.idempotency import compute_request_hash


async def create_payment(
    session: AsyncSession,
    amount: Decimal,
    currency: str,
    description: str | None,
    metadata: dict[str, Any] | None,
    webhook_url: str,
    idempotency_key: str,
) -> Payment:
    """Create a new payment with outbox event in a single transaction."""
    request_hash = compute_request_hash(amount, currency, description, metadata, webhook_url)

    payment = Payment(
        id=uuid.uuid4(),
        amount=amount,
        currency=currency,  # type: ignore[arg-type]
        description=description,
        metadata_=metadata,
        status=PaymentStatus.pending,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        webhook_url=webhook_url,
        notification_status=None,
        notification_attempts=0,
    )

    session.add(payment)
    await session.flush()

    # Create outbox event
    outbox_event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="payment.created",
        aggregate_id=payment.id,
        payload={
            "payment_id": str(payment.id),
            "amount": str(amount),
            "currency": currency,
            "status": PaymentStatus.pending.value,
        },
        status=OutboxStatus.pending,
        attempts=0,
    )
    session.add(outbox_event)

    return payment


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.id == payment_id))
    return result.scalar_one_or_none()


async def get_payment_by_idempotency_key(session: AsyncSession, idempotency_key: str) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()