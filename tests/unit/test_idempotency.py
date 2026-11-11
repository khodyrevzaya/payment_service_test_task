from __future__ import annotations

from decimal import Decimal

import pytest

from src.services.idempotency import canonical_json, compute_request_hash


class TestCanonicalJson:
    def test_sorted_keys(self):
        result = canonical_json({"b": 2, "a": 1})
        assert result == '{"a":1,"b":2}'

    def test_nested_dict(self):
        result = canonical_json({"outer": {"b": 2, "a": 1}})
        assert result == '{"outer":{"a":1,"b":2}}'

    def test_decimal_serialization(self):
        result = canonical_json({"amount": Decimal("100.50")})
        assert result == '{"amount":"100.50"}'


class TestComputeRequestHash:
    def test_same_input_same_hash(self):
        h1 = compute_request_hash(
            Decimal("100.50"), "RUB", "test", None, "https://example.com/webhook"
        )
        h2 = compute_request_hash(
            Decimal("100.50"), "RUB", "test", None, "https://example.com/webhook"
        )
        assert h1 == h2

    def test_different_amount_different_hash(self):
        h1 = compute_request_hash(
            Decimal("100.50"), "RUB", "test", None, "https://example.com/webhook"
        )
        h2 = compute_request_hash(
            Decimal("200.00"), "RUB", "test", None, "https://example.com/webhook"
        )
        assert h1 != h2

    def test_different_currency_different_hash(self):
        h1 = compute_request_hash(
            Decimal("100.50"), "RUB", "test", None, "https://example.com/webhook"
        )
        h2 = compute_request_hash(
            Decimal("100.50"), "USD", "test", None, "https://example.com/webhook"
        )
        assert h1 != h2

    def test_hash_is_64_chars(self):
        h = compute_request_hash(
            Decimal("100.50"), "RUB", "test", None, "https://example.com/webhook"
        )
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)