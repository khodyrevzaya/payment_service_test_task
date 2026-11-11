from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from faststream.exceptions import RejectMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import async_session_factory
from src.db.enums import NotificationStatus, PaymentStatus
from src.db.models import Payment
from src.services.webhook import send_webhook

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1  # seconds: 1s → 2s → 4s


def _deterministic_outcome(payment_id: uuid.UUID) -> tuple[bool, float]:
    """Deterministic payment outcome based on payment_id hash."""
    h = hashlib.sha256(str(payment_id).encode()).hexdigest()
    success = int(h[:2], 16) % 100 < 100  # 100% success for testing
    delay = 2 + int(h[2:4], 16) % 4
    return success, delay


async def handle_payment_created(payment_id: str) -> None:
    """Process a payment.created event."""
    pid = uuid.UUID(payment_id)
    logger.info("Processing payment", extra={"payment_id": payment_id})

    async with async_session_factory() as session:
        result = await session.execute(
            select(Payment).where(Payment.id == pid).with_for_update()
        )
        payment = result.scalar_one_or_none()

        if payment is None:
            logger.error("Payment not found", extra={"payment_id": payment_id})
            raise ValueError(f"Payment {payment_id} not found in database")

        # Idempotency check: if already terminal and webhook delivered, skip
        if payment.status in (PaymentStatus.succeeded, PaymentStatus.failed):
            if payment.notification_status == NotificationStatus.delivered:
                logger.info("Payment already processed and notified, skipping", extra={"payment_id": payment_id})
                return
            # Terminal but webhook not delivered — skip emulation, go to webhook
            logger.info("Payment already processed, retrying webhook", extra={"payment_id": payment_id})
        else:
            # Emulate payment processing
            success, delay = _deterministic_outcome(pid)
            logger.info(
                "Emulating payment",
                extra={"payment_id": payment_id, "success": success, "delay": delay},
            )
            await asyncio.sleep(delay)

            payment.status = PaymentStatus.succeeded if success else PaymentStatus.failed
            payment.processed_at = datetime.now(timezone.utc)

        # Send webhook if not yet delivered
        if payment.notification_status != NotificationStatus.delivered:
            if payment.notification_event_id is None:
                payment.notification_event_id = uuid.uuid4()

            result = await send_webhook(
                webhook_url=payment.webhook_url,
                payment_id=str(payment.id),
                status=payment.status.value,
                amount=str(payment.amount),
                currency=payment.currency.value,
                processed_at=payment.processed_at.isoformat() if payment.processed_at else "",
                event_id=str(payment.notification_event_id),
            )

            payment.notification_attempts = result["attempts"]
            payment.notification_last_error = result["last_error"]

            if result["success"]:
                payment.notification_status = NotificationStatus.delivered
            else:
                payment.notification_status = NotificationStatus.exhausted

        await session.commit()
        logger.info(
            "Payment processing completed",
            extra={
                "payment_id": payment_id,
                "status": payment.status.value,
                "notification": payment.notification_status.value if payment.notification_status else "none",
            },
        )


async def handle_payment_created_with_retry(payment_id: str) -> None:
    """Process payment with exponential backoff retry.

    Retries up to MAX_RETRIES times with delays: 1s → 2s → 4s.
    After exhausting all retries, raises RejectMessage to send the message to DLQ.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            await handle_payment_created(payment_id)
            return  # success → message will be acked
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Retrying payment processing",
                    extra={
                        "payment_id": payment_id,
                        "attempt": attempt + 1,
                        "max_retries": MAX_RETRIES,
                        "delay": delay,
                        "error": str(e),
                    },
                )
                await asyncio.sleep(delay)

    logger.error(
        "Payment processing exhausted all retries, sending to DLQ",
        extra={
            "payment_id": payment_id,
            "attempts": MAX_RETRIES,
            "last_error": str(last_error),
        },
    )
    raise RejectMessage()