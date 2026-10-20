"""Webhook Stripe firmado, Sandbox-only y procesado antes de responder 2xx."""

from typing import Annotated, NoReturn

import stripe
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.servicios.stripe_membresias import (
    EVENTOS_STRIPE_MEMBRESIA,
    StripeMembresiasError,
    StripeNoConfiguradoError,
    crear_cliente_stripe,
    procesar_evento_stripe,
)

RUTA_STRIPE_WEBHOOK = "/api/stripe/webhook"
TAMANO_MAXIMO_WEBHOOK = 1_048_576
router = APIRouter(tags=["stripe-webhooks"])


def _error_webhook_no_disponible() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="El webhook no pudo procesarse. Stripe puede reintentar.",
        headers={"Cache-Control": "no-store"},
    ) from None


def _procesar_evento_firmado(evento: object, settings: object) -> None:
    """Ejecuta Stripe y PostgreSQL fuera del event loop y confirma antes del ACK."""

    db: Session = SessionLocal()
    try:
        procesar_evento_stripe(
            db,
            crear_cliente_stripe(settings),  # type: ignore[arg-type]
            settings,  # type: ignore[arg-type]
            evento=evento,
        )
    finally:
        db.close()


@router.post(RUTA_STRIPE_WEBHOOK)
async def recibir_webhook_stripe(
    request: Request,
    response: Response,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    secreto = settings.stripe_webhook_secret
    if secreto is None:
        _error_webhook_no_disponible()
    if stripe_signature is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firma Stripe invalida.",
            headers={"Cache-Control": "no-store"},
        )
    payload = await request.body()
    if len(payload) > TAMANO_MAXIMO_WEBHOOK:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Evento demasiado grande.",
            headers={"Cache-Control": "no-store"},
        )
    try:
        evento = stripe.Webhook.construct_event(
            payload,
            stripe_signature,
            secreto.get_secret_value(),
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firma Stripe invalida.",
            headers={"Cache-Control": "no-store"},
        ) from None

    if getattr(evento, "livemode", None) is not False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se aceptan eventos de Stripe Sandbox.",
            headers={"Cache-Control": "no-store"},
        )
    if getattr(evento, "type", None) not in EVENTOS_STRIPE_MEMBRESIA:
        return {"received": True}
    if settings.stripe_api_key is None:
        _error_webhook_no_disponible()

    try:
        await run_in_threadpool(_procesar_evento_firmado, evento, settings)
    except (StripeNoConfiguradoError, StripeMembresiasError, stripe.StripeError):
        _error_webhook_no_disponible()
    except SQLAlchemyError:
        _error_webhook_no_disponible()
    except Exception:
        _error_webhook_no_disponible()
    return {"received": True}


__all__ = ["RUTA_STRIPE_WEBHOOK", "router", "recibir_webhook_stripe"]
