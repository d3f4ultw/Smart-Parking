"""Rutas HTTP de login, sesion y cierre de cuenta cliente."""

from typing import Annotated, NoReturn
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
from app.esquemas.autenticacion_clientes import (
    ClienteSesion,
    RespuestaLoginCliente,
    RespuestaLogoutCliente,
    RespuestaSesionCliente,
    SolicitudLoginCliente,
)
from app.models import CuentaCliente
from app.seguridad.contrasenas import HASH_DUMMY_CONTRASENA, verificar_contrasena
from app.seguridad.correos import (
    CorreoInvalidoError,
    huella_correo,
    normalizar_correo,
)
from app.seguridad.limitador_clientes import limitador_autenticacion_clientes
from app.servicios.autenticacion_clientes import (
    crear_sesion_cliente,
    revocar_sesion_cliente_actual,
)

RUTA_AUTENTICACION_CLIENTE = "/api/clientes/autenticacion"
RUTA_LOGIN_CLIENTE = f"{RUTA_AUTENTICACION_CLIENTE}/login"
RUTA_ME_CLIENTE = f"{RUTA_AUTENTICACION_CLIENTE}/me"
RUTA_LOGOUT_CLIENTE = f"{RUTA_AUTENTICACION_CLIENTE}/logout"
DETALLE_CREDENCIALES_INVALIDAS = "Credenciales invalidas"
DETALLE_DEMASIADOS_INTENTOS = "Demasiados intentos"
DETALLE_ORIGEN_NO_AUTORIZADO = "Origen no autorizado"

router = APIRouter(
    prefix=RUTA_AUTENTICACION_CLIENTE,
    tags=["autenticacion-clientes"],
)


def _mismo_origen(request: Request) -> bool:
    """Compara Origin exacto con el origen configurado para la aplicación."""

    origen = request.headers.get("origin")
    configurado = urlsplit(get_settings().app_public_url)
    esperado = f"{configurado.scheme}://{configurado.netloc}"
    return bool(configurado.scheme and configurado.netloc) and origen == esperado


def _exigir_origen(request: Request) -> None:
    if not _mismo_origen(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DETALLE_ORIGEN_NO_AUTORIZADO,
            headers=CABECERA_NO_CACHE,
        )


def _obtener_origen(request: Request) -> str:
    """Usa solo la dirección remota directa, nunca cabeceras reenviadas."""

    return request.client.host if request.client is not None else "desconocido"


def _error_login(codigo: int, detalle: str) -> NoReturn:
    raise HTTPException(
        status_code=codigo,
        detail=detalle,
        headers=CABECERA_NO_CACHE,
    )


def _limpiar_cookie_cliente(response: Response) -> None:
    """Expira solo la cookie que representa sesiones de cliente."""

    settings = get_settings()
    response.delete_cookie(
        key=settings.customer_session_cookie_name,
        path="/",
        secure=settings.customer_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/login", response_model=RespuestaLoginCliente)
def login_cliente(
    solicitud: SolicitudLoginCliente,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLoginCliente:
    """Autentica una cuenta activa y fija el token únicamente en cookie."""

    response.headers.update(CABECERA_NO_CACHE)
    _exigir_origen(request)

    try:
        correo_normalizado = normalizar_correo(solicitud.correo)
    except CorreoInvalidoError:
        huella = huella_correo(solicitud.correo.strip().casefold())
        if not limitador_autenticacion_clientes.permitir(
            _obtener_origen(request),
            huella,
        ):
            _error_login(status.HTTP_429_TOO_MANY_REQUESTS, DETALLE_DEMASIADOS_INTENTOS)
        verificar_contrasena(solicitud.contrasena, HASH_DUMMY_CONTRASENA)
        _error_login(status.HTTP_401_UNAUTHORIZED, DETALLE_CREDENCIALES_INVALIDAS)

    if not limitador_autenticacion_clientes.permitir(
        _obtener_origen(request),
        huella_correo(correo_normalizado),
    ):
        _error_login(status.HTTP_429_TOO_MANY_REQUESTS, DETALLE_DEMASIADOS_INTENTOS)

    settings = get_settings()
    try:
        resultado = crear_sesion_cliente(
            db,
            correo_normalizado=correo_normalizado,
            contrasena=solicitud.contrasena,
            duracion_minutos=settings.customer_session_duration_minutes,
        )
    except SQLAlchemyError:
        _error_login(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")

    if resultado is None:
        _error_login(status.HTTP_401_UNAUTHORIZED, DETALLE_CREDENCIALES_INVALIDAS)

    response.set_cookie(
        key=settings.customer_session_cookie_name,
        value=resultado.token,
        max_age=settings.customer_session_duration_minutes * 60,
        path="/",
        secure=settings.customer_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RespuestaLoginCliente(estado="credenciales_validas")


@router.get("/me", response_model=RespuestaSesionCliente)
def obtener_sesion_cliente(
    response: Response,
    cuenta: Annotated[CuentaCliente, Depends(exigir_cuenta_cliente)],
) -> RespuestaSesionCliente:
    """Expone los datos básicos de la cuenta asociada a la cookie cliente."""

    response.headers.update(CABECERA_NO_CACHE)
    return RespuestaSesionCliente(
        autenticado=True,
        cliente=ClienteSesion(
            nombre=cuenta.nombre,
            apellido_paterno=cuenta.apellido_paterno,
            apellido_materno=cuenta.apellido_materno,
            correo=cuenta.correo,
            correo_verificado=cuenta.correo_verificado,
        ),
    )


@router.post("/logout", response_model=RespuestaLogoutCliente)
def logout_cliente(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLogoutCliente:
    """Revoca la sesión indicada por la cookie cliente y la expira."""

    response.headers.update(CABECERA_NO_CACHE)
    _exigir_origen(request)
    settings = get_settings()
    token = request.cookies.get(settings.customer_session_cookie_name)
    try:
        if token:
            revocar_sesion_cliente_actual(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    _limpiar_cookie_cliente(response)
    return RespuestaLogoutCliente(estado="sesion_cerrada")


__all__ = [
    "RUTA_AUTENTICACION_CLIENTE",
    "RUTA_LOGIN_CLIENTE",
    "RUTA_LOGOUT_CLIENTE",
    "RUTA_ME_CLIENTE",
    "login_cliente",
    "logout_cliente",
    "obtener_sesion_cliente",
    "router",
]
