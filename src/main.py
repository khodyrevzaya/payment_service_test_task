from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.errors import RequestIDMiddleware, create_error_response
from src.api.v1.router import router as v1_router
from src.db.base import async_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Payment Service",
    description="Асинхронный сервис процессинга платежей",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(RequestIDMiddleware)

# Routers
app.include_router(v1_router)


# Health check
@app.get("/health")
async def health_check():
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})


# Exception handlers
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    return create_error_response(401, "invalid_api_key", "Invalid or missing API key", request_id)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    return create_error_response(404, "not_found", str(exc), request_id)


@app.exception_handler(409)
async def conflict_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    return create_error_response(409, "idempotency_conflict", str(exc), request_id)


@app.exception_handler(422)
async def validation_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    return create_error_response(422, "validation_error", str(exc), request_id)