from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.base import async_session_factory

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyAuth")


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    if api_key is None or not secrets.compare_digest(api_key, settings.api_key):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session