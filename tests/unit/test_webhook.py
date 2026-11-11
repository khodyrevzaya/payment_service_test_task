from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.webhook import _is_retryable, send_webhook


class TestIsRetryable:
    def test_408_is_retryable(self):
        assert _is_retryable(408) is True

    def test_429_is_retryable(self):
        assert _is_retryable(429) is True

    def test_500_is_retryable(self):
        assert _is_retryable(500) is True

    def test_502_is_retryable(self):
        assert _is_retryable(502) is True

    def test_503_is_retryable(self):
        assert _is_retryable(503) is True

    def test_200_is_not_retryable(self):
        assert _is_retryable(200) is False

    def test_400_is_not_retryable(self):
        assert _is_retryable(400) is False

    def test_404_is_not_retryable(self):
        assert _is_retryable(404) is False


class TestSendWebhook:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await send_webhook(
                webhook_url="https://example.com/webhook",
                payment_id="550e8400-e29b-41d4-a716-446655440000",
                status="succeeded",
                amount="100.50",
                currency="RUB",
                processed_at="2024-01-01T00:00:00+00:00",
            )

        assert result["success"] is True
        assert result["attempts"] == 1
        assert result["last_error"] is None

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        mock_fail = AsyncMock()
        mock_fail.status_code = 500

        mock_success = AsyncMock()
        mock_success.status_code = 200

        with patch("httpx.AsyncClient.post", side_effect=[mock_fail, mock_fail, mock_success]):
            result = await send_webhook(
                webhook_url="https://example.com/webhook",
                payment_id="550e8400-e29b-41d4-a716-446655440000",
                status="succeeded",
                amount="100.50",
                currency="RUB",
                processed_at="2024-01-01T00:00:00+00:00",
            )

        assert result["success"] is True
        assert result["attempts"] == 3

    @pytest.mark.asyncio
    async def test_exhausted_after_3_retries(self):
        mock_fail = AsyncMock()
        mock_fail.status_code = 500

        with patch("httpx.AsyncClient.post", return_value=mock_fail):
            result = await send_webhook(
                webhook_url="https://example.com/webhook",
                payment_id="550e8400-e29b-41d4-a716-446655440000",
                status="succeeded",
                amount="100.50",
                currency="RUB",
                processed_at="2024-01-01T00:00:00+00:00",
            )

        assert result["success"] is False
        assert result["attempts"] == 3
        assert result["last_error"] is not None

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self):
        mock_fail = AsyncMock()
        mock_fail.status_code = 400

        with patch("httpx.AsyncClient.post", return_value=mock_fail):
            result = await send_webhook(
                webhook_url="https://example.com/webhook",
                payment_id="550e8400-e29b-41d4-a716-446655440000",
                status="succeeded",
                amount="100.50",
                currency="RUB",
                processed_at="2024-01-01T00:00:00+00:00",
            )

        assert result["success"] is False
        assert result["attempts"] == 1  # no retry on 4xx
        assert result["last_error"] is not None

    @pytest.mark.asyncio
    async def test_connection_error_retry(self):
        mock_success = AsyncMock()
        mock_success.status_code = 200

        import httpx

        with patch(
            "httpx.AsyncClient.post",
            side_effect=[httpx.ConnectError("connection refused"), mock_success],
        ):
            result = await send_webhook(
                webhook_url="https://example.com/webhook",
                payment_id="550e8400-e29b-41d4-a716-446655440000",
                status="succeeded",
                amount="100.50",
                currency="RUB",
                processed_at="2024-01-01T00:00:00+00:00",
            )

        assert result["success"] is True
        assert result["attempts"] == 2