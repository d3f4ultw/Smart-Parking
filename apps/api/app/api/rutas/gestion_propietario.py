"""API aislada de la sesion temporal de gestion inicial de OWNER."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, NoReturn
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.correo.errores import ConfiguracionSMTPInvalidaError, ErrorCorreo
from app.correo.mensajes import (
    construir_mensaje_confirmacion_desvinculacion_propietario,
    construir_mensaje_invitacion_propietario,
)
from app.correo.transportes import crear_transporte_correo
from app.esquemas.gestion_propietario import (
    RespuestaConfirmacionDesvinculacionPropietario,
    RespuestaEstadoGestionPropietario,
    RespuestaInscripcionGestionPropietario,
    RespuestaSesionGestionPropietario,
    RespuestaSolicitudDesvinculacionPropietario,
    ResumenOwnerGestionPropietario,
    SolicitudConfirmacionDesvinculacionPropietario,
    SolicitudDesvinculacionGestionPropietario,
    SolicitudInscripcionGestionPropietario,
    SolicitudReclamoGestionPropietario,
)
from app.models import InscripcionPropietario
from app.seguridad.correos import CorreoInvalidoError
from app.seguridad.limitador import (
    limitador_confirmacion_desvinculacion,
    limitador_solicitud_desvinculacion,
)
from app.servicios.desvinculacion_propietario import (
    ConfirmacionDesvinculacionNoValidaError,
    ConfirmacionDesvinculacionPendienteError,
    ContrasenaAdministrativaIncorrectaError,
    LimiteSolicitudesDesvinculacionError,
    PropietarioNoDisponibleError,
    confirmar_desvinculacion_propietario,
    hash_token_desvinculacion,
    obtener_id_owner_activo,
    obtener_owner_activo,
    obtener_segundos_desvinculacion_vigente,
    solicitar_desvinculacion_propietario,
)
from app.servicios.gestion_propietario import (
    CodigoApareamientoInvalido,
    SesionGestionPropietarioNoDisponible,
    reclamar_sesion_gestion,
    renovar_sesion_gestion,
    validar_sesion_gestion,
)
from app.servicios.propietario import (
    InscripcionPropietarioNoDisponible,
    InscripcionPropietarioYaEnCurso,
    LimiteReenviosPropietario,
    ReenvioPropietarioEnEspera,
    iniciar_inscripcion_propietario,
    listar_estados_inscripciones_propietario,
)

RUTA_GESTION_PROPIETARIO = "/api/gestion-propietario/v1"
NOMBRE_COOKIE_GESTION_PROPIETARIO = "smart_parking_owner_management"
# The Nitro BFF and SSR page use different paths; the dedicated cookie name and
# server-side API authorization keep this host-only credential purpose-bound.
PATH_COOKIE_GESTION_PROPIETARIO = "/"
CABECERAS_GESTION = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}
router = APIRouter(prefix=RUTA_GESTION_PROPIETARIO, tags=["gestion-propietario"])


def _error_no_disponible() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="La autorizacion de gestion no esta disponible.",
        headers=CABECERAS_GESTION,
    )


def _error_no_autorizado() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesion de gestion no esta activa.",
        headers=CABECERAS_GESTION,
    )


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="No se pudo completar la operacion.",
        headers=CABECERAS_GESTION,
    )


def _mismo_origen(request: Request, settings: Settings) -> bool:
    """Requiere que toda escritura venga del origen Web configurado."""

    origen = request.headers.get("origin")
    configurado = urlsplit(settings.app_public_url)
    origen_esperado = f"{configurado.scheme}://{configurado.netloc}"
    return origen == origen_esperado


def _obtener_origen(request: Request) -> str:
    """Obtiene la IP remota sin confiar en cabeceras reenviadas."""

    return request.client.host if request.client is not None else "desconocido"


def exigir_origen_gestion(request: Request) -> None:
    """Bloquea escrituras y claims que no provengan del origen de la aplicacion."""

    if not _mismo_origen(request, get_settings()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no autorizado.",
            headers=CABECERAS_GESTION,
        )


def exigir_sesion_gestion(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> int:
    """Autoriza cada accion privada solo con la cookie temporal del navegador."""

    credencial = request.cookies.get(NOMBRE_COOKIE_GESTION_PROPIETARIO)
    try:
        id_sesion = validar_sesion_gestion(db, credencial=credencial)
    except SQLAlchemyError:
        _error_interno()
    if id_sesion is None:
        _error_no_autorizado()
    return id_sesion


@router.post("/claim", response_model=RespuestaSesionGestionPropietario)
def reclamar_ticket_gestion(
    solicitud: SolicitudReclamoGestionPropietario,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSesionGestionPropietario:
    """Vincula el primer navegador y conserva el URL durante todo el lease."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)
    credencial_actual = request.cookies.get(NOMBRE_COOKIE_GESTION_PROPIETARIO)
    try:
        resultado = reclamar_sesion_gestion(
            db,
            ticket=solicitud.ticket,
            codigo_apareamiento=solicitud.codigo_apareamiento,
            credencial_actual=credencial_actual,
        )
    except CodigoApareamientoInvalido, SesionGestionPropietarioNoDisponible:
        _error_no_disponible()
    except SQLAlchemyError:
        _error_interno()

    if resultado.credencial_nueva is not None:
        settings = get_settings()
        response.set_cookie(
            key=NOMBRE_COOKIE_GESTION_PROPIETARIO,
            value=resultado.credencial_nueva,
            path=PATH_COOKIE_GESTION_PROPIETARIO,
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
    return RespuestaSesionGestionPropietario(activa=True)


@router.get("/sesion", response_model=RespuestaSesionGestionPropietario)
def resolver_sesion_gestion(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSesionGestionPropietario:
    """Resuelve la cookie sin conceder autorizacion de aplicacion ordinaria."""

    response.headers.update(CABECERAS_GESTION)
    try:
        id_sesion = validar_sesion_gestion(
            db,
            credencial=request.cookies.get(NOMBRE_COOKIE_GESTION_PROPIETARIO),
        )
    except SQLAlchemyError:
        _error_interno()
    return RespuestaSesionGestionPropietario(activa=id_sesion is not None)


@router.post("/latido", response_model=RespuestaSesionGestionPropietario)
def latido_sesion_gestion(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSesionGestionPropietario:
    """Renueva el lease deslizante sin asignarle vencimiento absoluto."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)
    credencial = request.cookies.get(NOMBRE_COOKIE_GESTION_PROPIETARIO)
    try:
        activa = renovar_sesion_gestion(db, credencial=credencial or "")
    except SQLAlchemyError:
        _error_interno()
    if not activa:
        _error_no_autorizado()
    return RespuestaSesionGestionPropietario(activa=True)


@router.get("/estado", response_model=RespuestaEstadoGestionPropietario)
def consultar_estado_gestion(
    response: Response,
    _id_sesion: Annotated[int, Depends(exigir_sesion_gestion)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEstadoGestionPropietario:
    """Lee el estado de OWNER sin enviar correo ni modificar inscripciones."""

    response.headers.update(CABECERAS_GESTION)
    try:
        estados = listar_estados_inscripciones_propietario(db)
        owner = obtener_owner_activo(db)
        segundos_desvinculacion = (
            obtener_segundos_desvinculacion_vigente(db, usuario_id=owner.id)
            if owner is not None
            else 0
        )
    except SQLAlchemyError:
        _error_interno()
    return RespuestaEstadoGestionPropietario(
        owner_activo=owner is not None,
        desvinculacion_segundos_restantes=segundos_desvinculacion,
        owner=(
            ResumenOwnerGestionPropietario(
                nombre=" ".join(
                    parte.strip()
                    for parte in (
                        owner.nombre,
                        owner.apellido_paterno,
                        owner.apellido_materno,
                    )
                    if parte is not None and parte.strip()
                )
                or "Dueño",
                correo=owner.correo,
            )
            if owner is not None
            else None
        ),
        inscripciones=[
            RespuestaInscripcionGestionPropietario.model_validate(estado)
            for estado in estados
        ],
    )


def _entregar_enlace(settings: Settings):
    """Construye un emisor que solo entrega enlaces al transporte configurado."""

    transporte = crear_transporte_correo(settings)

    def entregar(correo: str, token: str) -> None:
        mensaje = construir_mensaje_invitacion_propietario(
            correo,
            token,
            settings=settings,
        )
        transporte.enviar(mensaje)

    return entregar


def _enviar_inscripcion(
    db: Session,
    *,
    correo: str,
    modo: Literal["nueva", "reenvio"],
) -> None:
    settings = get_settings()
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=_entregar_enlace(settings),
        modo=modo,
    )


def _entregar_enlace_desvinculacion(settings: Settings):
    """Entrega solo el mensaje del enlace de desvinculacion."""

    transporte = crear_transporte_correo(settings)

    def entregar(correo: str, token: str) -> None:
        mensaje = construir_mensaje_confirmacion_desvinculacion_propietario(
            correo,
            token,
            settings=settings,
        )
        transporte.enviar(mensaje)

    return entregar


@router.post(
    "/desvinculacion",
    response_model=RespuestaSolicitudDesvinculacionPropietario,
    status_code=status.HTTP_202_ACCEPTED,
)
def solicitar_desvinculacion_gestion(
    solicitud: SolicitudDesvinculacionGestionPropietario,
    request: Request,
    response: Response,
    _id_sesion: Annotated[int, Depends(exigir_sesion_gestion)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSolicitudDesvinculacionPropietario:
    """Valida la clave administrativa antes de enviar el enlace de un solo uso."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)

    try:
        id_owner = obtener_id_owner_activo(db)
    except SQLAlchemyError:
        _error_interno()
    huella_owner = hashlib.sha256(
        f"owner-unlink-request:{id_owner or 0}".encode()
    ).hexdigest()
    if not limitador_solicitud_desvinculacion.permitir(
        _obtener_origen(request),
        huella_owner,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Espera antes de solicitar otro correo.",
            headers=CABECERAS_GESTION,
        )

    try:
        settings = get_settings()
        solicitar_desvinculacion_propietario(
            db,
            contrasena_admin=solicitud.contrasena_admin,
            entregar_enlace=_entregar_enlace_desvinculacion(settings),
        )
    except ContrasenaAdministrativaIncorrectaError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La contraseña administrativa no es correcta.",
            headers=CABECERAS_GESTION,
        ) from None
    except ConfirmacionDesvinculacionPendienteError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya se envió un enlace vigente.",
            headers=CABECERAS_GESTION,
        ) from None
    except LimiteSolicitudesDesvinculacionError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Se alcanzó el límite temporal de correos.",
            headers=CABECERAS_GESTION,
        ) from None
    except PropietarioNoDisponibleError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La desvinculación no está disponible.",
            headers=CABECERAS_GESTION,
        ) from None
    except ConfiguracionSMTPInvalidaError, ErrorCorreo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo enviar el correo de confirmación.",
            headers=CABECERAS_GESTION,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    return RespuestaSolicitudDesvinculacionPropietario(
        estado="confirmacion_enviada"
    )


@router.post(
    "/desvinculacion/confirmar",
    response_model=RespuestaConfirmacionDesvinculacionPropietario,
)
def confirmar_desvinculacion_por_correo(
    solicitud: SolicitudConfirmacionDesvinculacionPropietario,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaConfirmacionDesvinculacionPropietario:
    """Completa la accion con el enlace sin exigir la cookie de gestion."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)
    huella_token = hash_token_desvinculacion(solicitud.token)
    if not limitador_confirmacion_desvinculacion.permitir(
        _obtener_origen(request),
        huella_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos.",
            headers=CABECERAS_GESTION,
        )

    try:
        confirmar_desvinculacion_propietario(db, token=solicitud.token)
    except ConfirmacionDesvinculacionNoValidaError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="El enlace venció o ya no está disponible.",
            headers=CABECERAS_GESTION,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    return RespuestaConfirmacionDesvinculacionPropietario(
        estado="dueno_desvinculado"
    )


def _convertir_error_inscripcion(error: Exception) -> NoReturn:
    if isinstance(error, ReenvioPropietarioEnEspera):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="El reenvio aun esta dentro del periodo de espera.",
            headers=CABECERAS_GESTION,
        ) from None
    if isinstance(error, LimiteReenviosPropietario):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Se agotaron los reenvios permitidos.",
            headers=CABECERAS_GESTION,
        ) from None
    if isinstance(error, InscripcionPropietarioYaEnCurso):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un proceso de inscripcion vigente.",
            headers=CABECERAS_GESTION,
        ) from None
    if isinstance(error, (InscripcionPropietarioNoDisponible, CorreoInvalidoError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede iniciar esta inscripcion.",
            headers=CABECERAS_GESTION,
        ) from None
    if isinstance(error, (ConfiguracionSMTPInvalidaError, ErrorCorreo)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo enviar el correo de verificacion.",
            headers=CABECERAS_GESTION,
        ) from None
    _error_interno()


@router.post("/inscripciones", status_code=status.HTTP_204_NO_CONTENT)
def iniciar_inscripcion_gestion(
    solicitud: SolicitudInscripcionGestionPropietario,
    request: Request,
    response: Response,
    _id_sesion: Annotated[int, Depends(exigir_sesion_gestion)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Inicia una solicitud nueva solo tras la accion explicita del operador."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)
    try:
        _enviar_inscripcion(db, correo=solicitud.correo, modo="nueva")
    except (
        ReenvioPropietarioEnEspera,
        LimiteReenviosPropietario,
        InscripcionPropietarioNoDisponible,
        InscripcionPropietarioYaEnCurso,
        CorreoInvalidoError,
        ConfiguracionSMTPInvalidaError,
        ErrorCorreo,
    ) as error:
        _convertir_error_inscripcion(error)
    except SQLAlchemyError:
        _error_interno()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/inscripciones/{id_inscripcion}/reenviar",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reenviar_inscripcion_gestion(
    id_inscripcion: int,
    request: Request,
    response: Response,
    _id_sesion: Annotated[int, Depends(exigir_sesion_gestion)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Reenvia un proceso concreto cuando sus reglas de negocio lo permiten."""

    response.headers.update(CABECERAS_GESTION)
    exigir_origen_gestion(request)
    inscripcion = db.scalar(
        select(InscripcionPropietario).where(
            InscripcionPropietario.id == id_inscripcion
        )
    )
    if inscripcion is None:
        _error_no_disponible()
    try:
        _enviar_inscripcion(db, correo=inscripcion.correo, modo="reenvio")
    except (
        ReenvioPropietarioEnEspera,
        LimiteReenviosPropietario,
        InscripcionPropietarioNoDisponible,
        CorreoInvalidoError,
        ConfiguracionSMTPInvalidaError,
        ErrorCorreo,
    ) as error:
        _convertir_error_inscripcion(error)
    except SQLAlchemyError:
        _error_interno()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


__all__ = [
    "CABECERAS_GESTION",
    "NOMBRE_COOKIE_GESTION_PROPIETARIO",
    "PATH_COOKIE_GESTION_PROPIETARIO",
    "RUTA_GESTION_PROPIETARIO",
    "exigir_sesion_gestion",
    "exigir_origen_gestion",
    "router",
]
