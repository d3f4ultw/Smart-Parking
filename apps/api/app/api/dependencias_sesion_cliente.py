"""Dependencia para autorizar operaciones con una sesion de cliente."""

from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import CuentaCliente
from app.servicios.autenticacion_clientes import obtener_cuenta_cliente_por_token

CABECERA_NO_CACHE = {"Cache-Control": "no-store"}
DETALLE_SESION_NO_AUTENTICADA = "No autenticado"


def _error_no_autenticado() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DETALLE_SESION_NO_AUTENTICADA,
        headers=CABECERA_NO_CACHE,
    )


def exigir_cuenta_cliente(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> CuentaCliente:
    """Obtiene la cuenta activa usando únicamente la cookie de cliente."""

    token = request.cookies.get(get_settings().customer_session_cookie_name)
    if not token:
        db.rollback()
        _error_no_autenticado()

    try:
        cuenta = obtener_cuenta_cliente_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    if cuenta is None:
        db.rollback()
        _error_no_autenticado()
    return cuenta


__all__ = ["exigir_cuenta_cliente"]
