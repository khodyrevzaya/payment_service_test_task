from __future__ import annotations

import enum


class Currency(str, enum.Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    exhausted = "exhausted"


class OutboxStatus(str, enum.Enum):
    pending = "pending"
    published = "published"