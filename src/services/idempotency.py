from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def canonical_json(data: dict[str, Any]) -> str:
    """Serialize dict to canonical JSON with sorted keys for consistent hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_request_hash(
    amount: Decimal,
    currency: str,
    description: str | None,
    metadata: dict[str, Any] | None,
    webhook_url: str,
) -> str:
    """Compute SHA-256 hash of the normalized request body."""
    payload = {
        "amount": str(amount),
        "currency": currency,
        "description": description,
        "metadata": metadata,
        "webhook_url": webhook_url,
    }
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode()).hexdigest()