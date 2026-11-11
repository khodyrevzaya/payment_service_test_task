from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator


class PaymentCreateRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=10**16, max_decimal_places=2)
    currency: str = Field(pattern=r"^(RUB|USD|EUR)$")
    description: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] | None = Field(default=None)
    webhook_url: str = Field(max_length=2048)

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("webhook_url must use HTTPS")
        return v


class PaymentCreateResponse(BaseModel):
    payment_id: UUID
    status: str
    created_at: datetime


class PaymentDetailResponse(BaseModel):
    id: UUID
    amount: Decimal
    currency: str
    description: str | None
    #metadata: dict[str, Any] | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    status: str
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    notification_status: str | None
    notification_attempts: int
    notification_last_error: str | None

    model_config = {"from_attributes": True}