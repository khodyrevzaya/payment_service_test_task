from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_api_key
from src.api.errors import create_error_response
from src.schemas.payment import PaymentCreateRequest, PaymentCreateResponse, PaymentDetailResponse
from src.services.idempotency import compute_request_hash
from src.services.payment_service import create_payment, get_payment, get_payment_by_idempotency_key

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("", status_code=202, response_model=PaymentCreateResponse)
async def create_payment_endpoint(
    request: Request,
    body: PaymentCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    api_key: str = Depends(verify_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    # Validate idempotency key format
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(status_code=422, detail="Invalid Idempotency-Key")

    request_hash = compute_request_hash(
        body.amount, body.currency, body.description, body.metadata, str(body.webhook_url)
    )

    # Check for existing payment with same idempotency key
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        if existing.request_hash == request_hash:
            # Same key, same body — idempotent replay
            response = PaymentCreateResponse(
                payment_id=existing.id,
                status=existing.status.value,
                created_at=existing.created_at,
            )
            # Return 202 with Idempotency-Replayed header
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=202,
                content=response.model_dump(mode="json"),
                headers={"Idempotency-Replayed": "true"},
            )
        else:
            # Same key, different body — conflict
            request_id = getattr(request.state, "request_id", None)
            return create_error_response(409, "idempotency_conflict", "Idempotency key reused with different body", request_id)

    # Create new payment
    try:
        payment = await create_payment(
            session=session,
            amount=body.amount,
            currency=body.currency,
            description=body.description,
            metadata=body.metadata,
            webhook_url=str(body.webhook_url),
            idempotency_key=idempotency_key,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Race condition: another request created payment with same key
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            if existing.request_hash == request_hash:
                from fastapi.responses import JSONResponse

                response = PaymentCreateResponse(
                    payment_id=existing.id,
                    status=existing.status.value,
                    created_at=existing.created_at,
                )
                return JSONResponse(
                    status_code=202,
                    content=response.model_dump(mode="json"),
                    headers={"Idempotency-Replayed": "true"},
                )
            else:
                request_id = getattr(request.state, "request_id", None)
                return create_error_response(409, "idempotency_conflict", "Idempotency key reused with different body", request_id)
        raise

    return PaymentCreateResponse(
        payment_id=payment.id,
        status=payment.status.value,
        created_at=payment.created_at,
    )


@router.get("/{payment_id}", response_model=PaymentDetailResponse)
async def get_payment_endpoint(
    payment_id: uuid.UUID,
    api_key: str = Depends(verify_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    payment = await get_payment(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    return PaymentDetailResponse.model_validate(payment)