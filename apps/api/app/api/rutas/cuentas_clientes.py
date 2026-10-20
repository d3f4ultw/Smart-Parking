"""Registro publico de cuentas de cliente, separado del acceso de personal."""

import re
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.esquemas.cuentas_clientes import (
    RespuestaRegistroCliente,
    SolicitudRegistroCliente,
)
from app.seguridad.contrasenas import ContrasenaInvalidaError
from app.seguridad.correos import huella_correo
from app.seguridad.limitador import LimitadorAutenticacion
from app.servicios.cuentas_clientes import registrar_cuenta_cliente

RUTA_REGISTRO_CLIENTE = "/api/clientes/registro"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}
DETALLE_REGISTRO_INVALIDO = "Solicitud invalida"
DETALLE_DEMASIADOS_REGISTROS = "Demasiadas solicitudes de registro"
DETALLE_REGISTRO_NO_DISPONIBLE = "El registro no esta disponible temporalmente"
CABECERA_HUELLA_ORIGEN = "x-sp-registration-origin"
PATRON_HUELLA_ORIGEN = re.compile(r"^[0-9a-f]{64}$")

router = APIRouter(prefix="/api/clientes", tags=["cuentas-clientes"])
limitador_registro_clientes = LimitadorAutenticacion()


def _obtener_origen(request: Request) -> str:
    """Usa la huella privada del BFF o el par de red directo sin cabeceras libres."""

    huella_origen = request.headers.get(CABECERA_HUELLA_ORIGEN, "")
    if PATRON_HUELLA_ORIGEN.fullmatch(huella_origen):
        return f"bff:{huella_origen}"
    return request.client.host if request.client is not None else "desconocido"


def _error_registro(codigo: int, detalle: str) -> NoReturn:
    raise HTTPException(
        status_code=codigo,
        detail=detalle,
        headers=CABECERA_NO_CACHE,
    ) from None


@router.post(
    "/registro",
    response_model=RespuestaRegistroCliente,
    status_code=status.HTTP_202_ACCEPTED,
)
def registrar_cliente(
    solicitud: SolicitudRegistroCliente,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaRegistroCliente:
    """Acepta una cuenta sin crear sesion, usuario de personal ni compra."""

    response.headers.update(CABECERA_NO_CACHE)
    if not limitador_registro_clientes.permitir(
        _obtener_origen(request),
        huella_correo(solicitud.correo),
    ):
        _error_registro(
            status.HTTP_429_TOO_MANY_REQUESTS,
            DETALLE_DEMASIADOS_REGISTROS,
        )

    try:
        registrar_cuenta_cliente(
            db,
            nombre=solicitud.nombre,
            apellido_paterno=solicitud.apellido_paterno,
            apellido_materno=solicitud.apellido_materno,
            correo=solicitud.correo,
            contrasena=solicitud.contrasena,
        )
    except ContrasenaInvalidaError:
        _error_registro(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            DETALLE_REGISTRO_INVALIDO,
        )
    except SQLAlchemyError:
        db.rollback()
        _error_registro(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            DETALLE_REGISTRO_NO_DISPONIBLE,
        )

    return RespuestaRegistroCliente()


__all__ = [
    "RUTA_REGISTRO_CLIENTE",
    "limitador_registro_clientes",
    "router",
]
