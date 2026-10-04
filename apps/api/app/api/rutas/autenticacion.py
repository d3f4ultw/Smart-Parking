"""Ruta HTTP para validar credenciales de ADMIN."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.autenticacion import (
    RespuestaLogin,
    RespuestaLogout,
    RespuestaSesionActual,
    SolicitudLogin,
    UsuarioSesion,
)
from app.models import RolUsuario
from app.seguridad.correos import CorreoInvalidoError, huella_correo, normalizar_correo
from app.seguridad.limitador import limitador_autenticacion
from app.servicios.autenticacion import (
    crear_sesion_usuario,
    obtener_usuario_por_token,
    revocar_sesion_actual,
)

RUTA_LOGIN = "/api/autenticacion/login"
RUTA_ME = "/api/autenticacion/me"
RUTA_LOGOUT = "/api/autenticacion/logout"
DETALLE_CREDENCIALES_INVALIDAS = "Credenciales invalidas"
DETALLE_DEMASIADOS_INTENTOS = "Demasiados intentos"
DETALLE_SESION_NO_AUTENTICADA = "No autenticado"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}

router = APIRouter(prefix="/api/autenticacion", tags=["autenticacion"])


def _obtener_origen(request: Request) -> str:
    """Obtiene el origen de red sin confiar en cabeceras reenviadas."""

    return request.client.host if request.client is not None else "desconocido"


def _error_login(codigo: int, detalle: str) -> NoReturn:
    raise HTTPException(
        status_code=codigo,
        detail=detalle,
        headers=CABECERA_NO_CACHE,
    )


def _error_sesion_no_autenticada() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DETALLE_SESION_NO_AUTENTICADA,
        headers=CABECERA_NO_CACHE,
    )


def _error_logout() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    )


@router.post("/login", response_model=RespuestaLogin)
def login(
    solicitud: SolicitudLogin,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLogin:
    """Autentica una cuenta elegible y emite su cookie de sesión."""

    response.headers.update(CABECERA_NO_CACHE)

    try:
        correo_normalizado = normalizar_correo(solicitud.correo)
    except CorreoInvalidoError:
        _error_login(status.HTTP_422_UNPROCESSABLE_CONTENT, "Solicitud invalida")

    if not limitador_autenticacion.permitir(
        _obtener_origen(request),
        huella_correo(correo_normalizado),
    ):
        _error_login(status.HTTP_429_TOO_MANY_REQUESTS, DETALLE_DEMASIADOS_INTENTOS)

    try:
        settings = get_settings()
        resultado_sesion = crear_sesion_usuario(
            db,
            correo=solicitud.correo,
            contrasena=solicitud.contrasena,
            correo_normalizado=correo_normalizado,
            duracion_minutos=settings.session_duration_minutes,
        )
    except SQLAlchemyError:
        _error_login(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")

    if resultado_sesion is None:
        _error_login(status.HTTP_401_UNAUTHORIZED, DETALLE_CREDENCIALES_INVALIDAS)

    response.set_cookie(
        key=settings.session_cookie_name,
        value=resultado_sesion.token,
        max_age=settings.session_duration_minutes * 60,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RespuestaLogin(
        estado="credenciales_validas",
        rol=resultado_sesion.rol.value,
    )


@router.get("/me", response_model=RespuestaSesionActual)
def me(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSesionActual:
    """Resuelve la sesión actual sin exponer el token ni campos internos."""

    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        _error_sesion_no_autenticada()

    try:
        usuario = obtener_usuario_por_token(db, token=token)
    except SQLAlchemyError:
        _error_sesion_no_autenticada()

    if usuario is None:
        _error_sesion_no_autenticada()

    return RespuestaSesionActual(
        autenticado=True,
        usuario=UsuarioSesion(
            nombre=usuario.nombre,
            apellido_paterno=usuario.apellido_paterno,
            apellido_materno=usuario.apellido_materno,
            correo=usuario.correo,
            rol=RolUsuario(usuario.rol).value,
        ),
    )


@router.post("/logout", response_model=RespuestaLogout)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLogout:
    """Revoca la sesión actual y expira su cookie sin revelar su existencia."""

    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)

    try:
        if token:
            revocar_sesion_actual(db, token=token)
    except SQLAlchemyError:
        _error_logout()

    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RespuestaLogout(estado="sesion_cerrada")


__all__ = [
    "CABECERA_NO_CACHE",
    "DETALLE_CREDENCIALES_INVALIDAS",
    "DETALLE_DEMASIADOS_INTENTOS",
    "DETALLE_SESION_NO_AUTENTICADA",
    "RUTA_LOGIN",
    "RUTA_LOGOUT",
    "RUTA_ME",
    "login",
    "logout",
    "me",
    "router",
]
