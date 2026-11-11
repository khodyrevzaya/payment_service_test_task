from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


class TestCreatePayment:
    @pytest.mark.asyncio
    async def test_create_payment_returns_202(
        self, client: AsyncClient, api_key_headers: dict, idempotency_key: str, payment_payload: dict
    ):
        headers = {**api_key_headers, "Idempotency-Key": idempotency_key}
        response = await client.post("/api/v1/payments", json=payment_payload, headers=headers)

        assert response.status_code == 202
        data = response.json()
        assert "payment_id" in data
        assert data["status"] == "pending"
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_idempotent_replay(
        self, client: AsyncClient, api_key_headers: dict, idempotency_key: str, payment_payload: dict
    ):
        headers = {**api_key_headers, "Idempotency-Key": idempotency_key}

        # First request
        r1 = await client.post("/api/v1/payments", json=payment_payload, headers=headers)
        assert r1.status_code == 202
        payment_id_1 = r1.json()["payment_id"]

        # Second request with same key and body
        r2 = await client.post("/api/v1/payments", json=payment_payload, headers=headers)
        assert r2.status_code == 202
        assert r2.headers.get("idempotency-replayed") == "true"
        assert r2.json()["payment_id"] == payment_id_1

    @pytest.mark.asyncio
    async def test_idempotency_conflict(
        self, client: AsyncClient, api_key_headers: dict, idempotency_key: str, payment_payload: dict
    ):
        headers = {**api_key_headers, "Idempotency-Key": idempotency_key}

        # First request
        r1 = await client.post("/api/v1/payments", json=payment_payload, headers=headers)
        assert r1.status_code == 202

        # Second request with same key but different body
        different_payload = {**payment_payload, "amount": "200.00"}
        r2 = await client.post("/api/v1/payments", json=different_payload, headers=headers)
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "idempotency_conflict"

    @pytest.mark.asyncio
    async def test_missing_api_key(self, client: AsyncClient, idempotency_key: str, payment_payload: dict):
        headers = {"Idempotency-Key": idempotency_key}
        response = await client.post("/api/v1/payments", json=payment_payload, headers=headers)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_idempotency_key(self, client: AsyncClient, api_key_headers: dict, payment_payload: dict):
        response = await client.post("/api/v1/payments", json=payment_payload, headers=api_key_headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_currency(self, client: AsyncClient, api_key_headers: dict, idempotency_key: str):
        headers = {**api_key_headers, "Idempotency-Key": idempotency_key}
        payload = {"amount": "100.50", "currency": "GBP", "webhook_url": "https://example.com/webhook"}
        response = await client.post("/api/v1/payments", json=payload, headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_payment(
        self, client: AsyncClient, api_key_headers: dict, idempotency_key: str, payment_payload: dict
    ):
        headers = {**api_key_headers, "Idempotency-Key": idempotency_key}
        create_resp = await client.post("/api/v1/payments", json=payment_payload, headers=headers)
        payment_id = create_resp.json()["payment_id"]

        get_resp = await client.get(f"/api/v1/payments/{payment_id}", headers=api_key_headers)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == payment_id
        assert data["status"] == "pending"
        assert data["amount"] == "100.50"
        assert data["currency"] == "RUB"

    @pytest.mark.asyncio
    async def test_get_payment_not_found(self, client: AsyncClient, api_key_headers: dict):
        random_id = str(uuid.uuid4())
        response = await client.get(f"/api/v1/payments/{random_id}", headers=api_key_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_concurrent_idempotency(
        self, client: AsyncClient, api_key_headers: dict, payment_payload: dict
    ):
        import asyncio

        key = str(uuid.uuid4())
        headers = {**api_key_headers, "Idempotency-Key": key}

        async def make_request():
            return await client.post("/api/v1/payments", json=payment_payload, headers=headers)

        # 10 concurrent requests with same idempotency key
        responses = await asyncio.gather(*[make_request() for _ in range(10)])

        # All should succeed (202 or 409 handled by idempotency)
        payment_ids = set()
        for r in responses:
            assert r.status_code in (202, 409)
            if r.status_code == 202:
                payment_ids.add(r.json()["payment_id"])

        # Only one unique payment_id should exist
        assert len(payment_ids) == 1