from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {408, 429}
RETRYABLE_RANGES = {(500, 600)}
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds
JITTER_MS = 250  # max jitter in milliseconds


def _is_retryable(status_code: int) -> bool:
    if status_code in RETRYABLE_STATUSES:
        return True
    for low, high in RETRYABLE_RANGES:
        if low <= status_code < high:
            return True
    return False


def _compute_hmac_signature(timestamp: str, body: str) -> str:
    payload = f"{timestamp}.{body}"
    sig = hmac.new(
        settings.webhook_hmac_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v1={sig}"


async def send_webhook(
    webhook_url: str,
    payment_id: str,
    status: str,
    amount: str,
    currency: str,
    processed_at: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    """
    Send webhook notification with retry logic.
    Returns: {"success": bool, "attempts": int, "last_error": str | None}
    """
    if event_id is None:
        event_id = str(uuid.uuid4())

    timestamp = str(int(time.time()))
    body_payload = {
        "event_id": event_id,
        "payment_id": payment_id,
        "status": status,
        "amount": amount,
        "currency": currency,
        "processed_at": processed_at,
    }

    import json

    body_str = json.dumps(body_payload, default=str)
    signature = _compute_hmac_signature(timestamp, body_str)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Id": event_id,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": signature,
    }

    last_error = None

    async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(webhook_url, content=body_str, headers=headers)

                if 200 <= response.status_code < 300:
                    logger.info(
                        "Webhook delivered successfully",
                        extra={"payment_id": payment_id, "event_id": event_id, "attempt": attempt + 1},
                    )
                    return {"success": True, "attempts": attempt + 1, "last_error": None}

                if _is_retryable(response.status_code):
                    last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                    logger.warning(
                        "Webhook retryable error",
                        extra={"payment_id": payment_id, "status_code": response.status_code, "attempt": attempt + 1},
                    )
                else:
                    # Non-retryable 4xx
                    last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                    logger.error(
                        "Webhook non-retryable error",
                        extra={"payment_id": payment_id, "status_code": response.status_code},
                    )
                    return {"success": False, "attempts": attempt + 1, "last_error": last_error}

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = str(e)
                logger.warning(
                    "Webhook connection error",
                    extra={"payment_id": payment_id, "error": last_error, "attempt": attempt + 1},
                )

            # Wait before retry with jitter
            if attempt < MAX_RETRIES - 1:
                import random

                jitter = random.uniform(0, JITTER_MS / 1000)
                delay = RETRY_DELAYS[attempt] + jitter
                await __import__("asyncio").sleep(delay)

    logger.error(
        "Webhook exhausted all retries",
        extra={"payment_id": payment_id, "event_id": event_id, "attempts": MAX_RETRIES},
    )
    return {"success": False, "attempts": MAX_RETRIES, "last_error": last_error}