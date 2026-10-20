"""Ruta autenticada para cambiar la contrasena de una cuenta cliente."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias_sesion_cliente import (
    CABECERA_NO_CACHE,
    exigir_cuenta_cliente,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.contrasena_clientes import (
    RespuestaCambioContrasena,
    SolicitudCambioContrasena,
)
from app.models import CuentaCliente
from app.servicios.contrasena_clientes import (
    SesionClienteNoVigenteError,
    cambiar_contrasena_cliente,
)

RUTA_CAMBIO_CONTRASENA_CLIENTE = "/api/clientes/contrasena"
DETALLE_ORIGEN_NO_AUTORIZADO = "Origen no autorizado"
DETALLE_SOLICITUD_INVALIDA = "La solicitud no es válida"
DETALLE_CONTRASENA_ACTUAL_INCORRECTA = "La contraseña actual es incorrecta"

router = APIRouter(tags=["contrasenas-clientes"])


def _mismo_origen(request: Request) -> bool:
    """Compara Origin completo con el origen público configurado."""

    origen = request.headers.get("origin")
    configurado = urlsplit(get_settings().app_public_url)
    esperado = f"{configurado.scheme}://{configurado.netloc}"
    return bool(configurado.scheme and configurado.netloc) and origen == esperado


def _esquema_cuerpo() -> dict[str, object]:
    """Publica el esquema en OpenAPI sin activar errores que reflejen secretos."""

    return SolicitudCambioContrasena.model_json_schema()


@router.post(
    RUTA_CAMBIO_CONTRASENA_CLIENTE,
    response_model=RespuestaCambioContrasena,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _esquema_cuerpo()}},
        }
    },
)
async def cambiar_contrasena(
    request: Request,
    response: Response,
    cuenta: Annotated[CuentaCliente, Depends(exigir_cuenta_cliente)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaCambioContrasena:
    """Cambia el hash y cierra las demas sesiones cliente vigentes."""

    response.headers.update(CABECERA_NO_CACHE)
    if not _mismo_origen(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DETALLE_ORIGEN_NO_AUTORIZADO,
            headers=CABECERA_NO_CACHE,
        )

    try:
        payload = await request.json()
        solicitud = SolicitudCambioContrasena.model_validate(payload)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=DETALLE_SOLICITUD_INVALIDA,
            headers=CABECERA_NO_CACHE,
        ) from None

    token_sesion_actual = request.cookies.get(
        get_settings().customer_session_cookie_name
    )
    if token_sesion_actual is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers=CABECERA_NO_CACHE,
        )

    try:
        resultado = cambiar_contrasena_cliente(
            db,
            cuenta_cliente_id=cuenta.id,
            token_sesion_actual=token_sesion_actual,
            contrasena_actual=solicitud.contrasena_actual,
            contrasena_nueva=solicitud.contrasena_nueva,
            confirmacion_contrasena_nueva=solicitud.confirmacion_contrasena_nueva,
        )
    except SesionClienteNoVigenteError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    if resultado is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DETALLE_CONTRASENA_ACTUAL_INCORRECTA,
            headers=CABECERA_NO_CACHE,
        )
    return RespuestaCambioContrasena()


__all__ = [
    "RUTA_CAMBIO_CONTRASENA_CLIENTE",
    "cambiar_contrasena",
    "router",
]
