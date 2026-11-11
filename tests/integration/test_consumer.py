from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.consumer.handler import _deterministic_outcome, handle_payment_created
from src.db.enums import NotificationStatus, PaymentStatus
from src.db.models import Payment


class TestDeterministicOutcome:
    def test_same_id_same_result(self):
        pid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        r1 = _deterministic_outcome(pid)
        r2 = _deterministic_outcome(pid)
        assert r1 == r2

    def test_different_ids_may_differ(self):
        pid1 = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        pid2 = uuid.UUID("660e8400-e29b-41d4-a716-446655440000")
        r1 = _deterministic_outcome(pid1)
        r2 = _deterministic_outcome(pid2)
        # They may or may not differ, but both should have valid ranges
        assert isinstance(r1[0], bool)
        assert 2 <= r1[1] <= 5
        assert isinstance(r2[0], bool)
        assert 2 <= r2[1] <= 5


class TestConsumerHandler:
    @pytest.mark.asyncio
    async def test_skip_already_delivered(self, db_session):
        """Payment already terminal and webhook delivered — should skip."""
        pid = uuid.uuid4()
        payment = Payment(
            id=pid,
            amount=100.50,
            currency="RUB",
            status=PaymentStatus.succeeded,
            idempotency_key="test-key-1",
            request_hash="abc123",
            webhook_url="https://example.com/webhook",
            notification_status=NotificationStatus.delivered,
            notification_attempts=1,
        )
        db_session.add(payment)
        await db_session.commit()

        with patch("src.consumer.handler.send_webhook") as mock_webhook:
            await handle_payment_created(str(pid))
            mock_webhook.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_webhook_for_terminal_not_delivered(self, db_session):
        """Payment terminal but webhook not delivered — should retry webhook only."""
        pid = uuid.uuid4()
        payment = Payment(
            id=pid,
            amount=100.50,
            currency="RUB",
            status=PaymentStatus.succeeded,
            idempotency_key="test-key-2",
            request_hash="abc123",
            webhook_url="https://example.com/webhook",
            notification_status=NotificationStatus.pending,
            notification_attempts=0,
        )
        db_session.add(payment)
        await db_session.commit()

        with patch(
            "src.consumer.handler.send_webhook",
            return_value={"success": True, "attempts": 1, "last_error": None},
        ) as mock_webhook:
            await handle_payment_created(str(pid))
            mock_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_pending_payment(self, db_session):
        """Pending payment should be emulated and webhook sent."""
        pid = uuid.uuid4()
        payment = Payment(
            id=pid,
            amount=100.50,
            currency="RUB",
            status=PaymentStatus.pending,
            idempotency_key="test-key-3",
            request_hash="abc123",
            webhook_url="https://example.com/webhook",
            notification_status=NotificationStatus.pending,
            notification_attempts=0,
        )
        db_session.add(payment)
        await db_session.commit()

        with patch(
            "src.consumer.handler.send_webhook",
            return_value={"success": True, "attempts": 1, "last_error": None},
        ) as mock_webhook:
            await handle_payment_created(str(pid))
            mock_webhook.assert_called_once()

        # Verify payment was updated
        await db_session.refresh(payment)
        assert payment.status in (PaymentStatus.succeeded, PaymentStatus.failed)
        assert payment.processed_at is not None
        assert payment.notification_status == NotificationStatus.delivered