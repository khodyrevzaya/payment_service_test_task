from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.payments import router as payments_router

router = APIRouter()
router.include_router(payments_router)