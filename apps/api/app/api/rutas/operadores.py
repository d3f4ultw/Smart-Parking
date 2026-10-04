"""Rutas ADMIN para consultar y administrar cuentas OPERADOR."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.correo.errores import ErrorCorreo
from app.correo.mensajes import (
    construir_mensaje_invitacion_operador,
    construir_mensaje_regeneracion_credenciales_operador,
)
from app.correo.transportes import crear_transporte_correo
from app.esquemas.operadores import (
    RespuestaAccionOperador,
    RespuestaCrearOperador,
    RespuestaListaOperadores,
    RespuestaOperador,
    SolicitudCrearOperador,
)
from app.models import Usuario
from app.servicios.autenticacion import obtener_usuario_admin_por_token
from app.servicios.eventos_operadores import (
    LimiteConexionesSSEError,
    ResultadoLoteEventosSSE,
    SesionAdminSSENoValidaError,
    admitir_conexion_sse_admin,
    cerrar_conexion_sse_admin,
    consultar_lote_eventos_sse,
    cursor_necesita_resync,
    obtener_marca_eventos,
)
from app.servicios.operadores import (
    CooldownReenvioInvitacionError,
    OperadorNoEncontradoError,
    OperadorNoPendienteError,
    OperadorNoPuedeRegenerarContrasenaError,
    OperadorYaActivoError,
    OperadorYaInactivoError,
    desactivar_operador,
    listar_operadores,
    obtener_cooldown_reenvio_operador,
    obtener_operador,
    reactivar_operador,
    reenviar_invitacion_operador,
    regenerar_contrasena_operador,
)
from app.servicios.usuarios import (
    CorreoInvalidoError,
    CorreoOperadorDuplicadoError,
    DatoOperadorInvalidoError,
    crear_operador,
)

RUTA_CREAR_OPERADOR = "/api/admin/operadores"
DETALLE_SESION_NO_AUTENTICADA = "No autenticado"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}
CABECERAS_SSE = {"Cache-Control": "no-store"}
INTERVALO_POLL_SSE = 1.0
INTERVALO_REVALIDACION_SSE = 10.0
INTERVALO_HEARTBEAT_SSE = 15.0

router = APIRouter(prefix=RUTA_CREAR_OPERADOR, tags=["admin"])


def _error_sesion_no_autenticada() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DETALLE_SESION_NO_AUTENTICADA,
        headers=CABECERA_NO_CACHE,
    )


def _exigir_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> int:
    """Autoriza la cookie persistida y devuelve el id del ADMIN autenticado."""

    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        db.rollback()
        _error_sesion_no_autenticada()

    try:
        usuario = obtener_usuario_admin_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        _error_sesion_no_autenticada()

    admin_usuario_id = usuario.id if usuario is not None else None
    db.rollback()
    if admin_usuario_id is None:
        _error_sesion_no_autenticada()
    return admin_usuario_id


@dataclass(frozen=True, slots=True)
class ContextoStreamOperadores:
    """Estado minimo de un stream; el token nunca se representa ni persiste."""

    admin_usuario_id: int
    token_sesion: str = field(repr=False)
    lease_id: UUID
    cursor: int
    marca_inicial: int
    requiere_resync: bool


def _error_cursor_sse() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Last-Event-ID invalido",
        headers=CABECERA_NO_CACHE,
    )


def _interpretar_cursor_sse(valor: str | None, marca: int) -> int:
    if valor is None:
        return marca
    if (
        not valor
        or len(valor) > 19
        or any(caracter < "0" or caracter > "9" for caracter in valor)
    ):
        _error_cursor_sse()
    cursor = int(valor)
    if cursor > marca:
        _error_cursor_sse()
    return cursor


def _preparar_contexto_stream_operadores(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db, scope="function")],
) -> ContextoStreamOperadores:
    """Autoriza, valida el cursor y reserva la lease antes de los headers SSE."""

    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        db.rollback()
        _error_sesion_no_autenticada()

    try:
        admin = obtener_usuario_admin_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        _error_sesion_no_autenticada()
    admin_usuario_id = admin.id if admin is not None else None
    db.rollback()
    if admin_usuario_id is None:
        _error_sesion_no_autenticada()

    cabeceras_cursor = request.headers.getlist("last-event-id")
    if len(cabeceras_cursor) > 1:
        _error_cursor_sse()
    valor_cursor = cabeceras_cursor[0] if cabeceras_cursor else None

    try:
        marca, primer_evento = obtener_marca_eventos(db)
        db.rollback()
        cursor = _interpretar_cursor_sse(valor_cursor, marca)
        requiere_resync = valor_cursor is not None and cursor_necesita_resync(
            cursor,
            marca,
            primer_evento,
        )
        lease_id = admitir_conexion_sse_admin(
            db,
            admin_usuario_id=admin_usuario_id,
            token_sesion=token,
        )
    except SesionAdminSSENoValidaError:
        db.rollback()
        _error_sesion_no_autenticada()
    except LimiteConexionesSSEError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Se alcanzo el limite de conexiones en tiempo real.",
            headers={
                **CABECERA_NO_CACHE,
                "Retry-After": str(error.reintentar_en),
            },
        ) from None
    except (RuntimeError, SQLAlchemyError):
        db.rollback()
        _error_interno()

    response.headers.update(CABECERAS_SSE)
    return ContextoStreamOperadores(
        admin_usuario_id=admin_usuario_id,
        token_sesion=token,
        lease_id=lease_id,
        cursor=cursor,
        marca_inicial=marca,
        requiere_resync=requiere_resync,
    )


def _consultar_lote_en_sesion(
    *,
    contexto: ContextoStreamOperadores,
    cursor: int,
    revalidar_sesion: bool,
    renovar_conexion: bool,
) -> ResultadoLoteEventosSSE:
    with SessionLocal() as db:
        return consultar_lote_eventos_sse(
            db,
            admin_usuario_id=contexto.admin_usuario_id,
            token_sesion=contexto.token_sesion,
            lease_id=contexto.lease_id,
            cursor=cursor,
            revalidar_sesion=revalidar_sesion,
            renovar_conexion=renovar_conexion,
        )


def _cerrar_lease_en_sesion(contexto: ContextoStreamOperadores) -> None:
    with SessionLocal() as db:
        cerrar_conexion_sse_admin(
            db,
            admin_usuario_id=contexto.admin_usuario_id,
            lease_id=contexto.lease_id,
        )


async def _generar_eventos_operadores(
    contexto: ContextoStreamOperadores,
) -> AsyncGenerator[ServerSentEvent]:
    """Consulta eventos en sesiones breves y cierra la lease al desconectar."""

    reloj = asyncio.get_running_loop()
    ahora = reloj.time()
    ultima_revalidacion = ahora - INTERVALO_REVALIDACION_SSE
    ultima_renovacion = ahora - INTERVALO_REVALIDACION_SSE
    ultimo_heartbeat = ahora
    cursor = contexto.cursor

    try:
        if contexto.requiere_resync:
            cursor = contexto.marca_inicial
            yield ServerSentEvent(
                id=str(cursor),
                event="resync",
                data={
                    "ultimo_id": cursor,
                    "motivo": "historial_expirado",
                },
            )

        while True:
            ahora = reloj.time()
            debe_revalidar = ahora - ultima_revalidacion >= INTERVALO_REVALIDACION_SSE
            debe_renovar = ahora - ultima_renovacion >= INTERVALO_REVALIDACION_SSE
            try:
                lote = await asyncio.to_thread(
                    _consultar_lote_en_sesion,
                    contexto=contexto,
                    cursor=cursor,
                    revalidar_sesion=debe_revalidar,
                    renovar_conexion=debe_renovar,
                )
            except (RuntimeError, SQLAlchemyError):
                return

            ahora = reloj.time()
            if debe_revalidar:
                ultima_revalidacion = ahora
            if debe_renovar:
                ultima_renovacion = ahora
            if not lote.autorizado:
                return

            if lote.requiere_resync:
                cursor = lote.marca
                yield ServerSentEvent(
                    id=str(cursor),
                    event="resync",
                    data={
                        "ultimo_id": cursor,
                        "motivo": "historial_expirado",
                    },
                )
            else:
                for evento in lote.eventos:
                    cursor = evento.id
                    yield ServerSentEvent(
                        id=str(evento.id),
                        event=evento.tipo,
                        data={
                            "operador_id": evento.operador_id,
                            "ocurrido_en": evento.ocurrido_en,
                        },
                    )

            ahora = reloj.time()
            if ahora - ultimo_heartbeat >= INTERVALO_HEARTBEAT_SSE:
                ultimo_heartbeat = ahora
                yield ServerSentEvent(comment="keepalive")

            await asyncio.sleep(0 if lote.eventos else INTERVALO_POLL_SSE)
    finally:
        tarea_limpieza = asyncio.create_task(
            asyncio.to_thread(_cerrar_lease_en_sesion, contexto)
        )
        try:
            await asyncio.shield(tarea_limpieza)
        except asyncio.CancelledError:
            try:
                await tarea_limpieza
            finally:
                raise
        except Exception:
            # La expiracion de 45 segundos limpia una lease si la BD no responde.
            pass


def _error_operador_no_encontrado() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Operador no encontrado",
        headers=CABECERA_NO_CACHE,
    )


def _error_operador_ya_inactivo() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="El operador ya está inactivo",
        headers=CABECERA_NO_CACHE,
    )


def _error_operador_ya_activo() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="El operador ya está activo",
        headers=CABECERA_NO_CACHE,
    )


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    )


@router.get("", response_model=RespuestaListaOperadores)
def listar_operadores_endpoint(
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
    pagina: Annotated[int, Query(ge=1)] = 1,
) -> RespuestaListaOperadores:
    """Lista una pagina de campos seguros de cuentas OPERADOR para ADMIN."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        marca_eventos, _primer_evento = obtener_marca_eventos(db)
        resultado = listar_operadores(db, pagina)
        return RespuestaListaOperadores(
            operadores=[
                RespuestaOperador.model_validate(operador)
                for operador in resultado.operadores
            ],
            pagina=resultado.pagina,
            tamano_pagina=resultado.tamano_pagina,
            total=resultado.total,
            total_paginas=resultado.total_paginas,
            cursor_eventos=str(marca_eventos),
        )
    except SQLAlchemyError:
        _error_interno()


@router.get("/eventos", response_class=EventSourceResponse)
async def eventos_operadores_endpoint(
    contexto: Annotated[
        ContextoStreamOperadores,
        Depends(_preparar_contexto_stream_operadores, scope="function"),
    ],
) -> AsyncIterator[ServerSentEvent]:
    """Inicia el stream privado de cambios visibles para cuentas ADMIN."""

    async for evento in _generar_eventos_operadores(contexto):
        yield evento


@router.get("/{operador_id}", response_model=RespuestaOperador)
def obtener_operador_endpoint(
    operador_id: int,
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaOperador:
    """Muestra la vista segura de un OPERADOR existente."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        operador = obtener_operador(db, operador_id)
        if operador.esta_activo and operador.estado_cuenta == "pendiente_activacion":
            cooldown = obtener_cooldown_reenvio_operador(
                db,
                operador_id,
                cooldown_segundos=(get_settings().activacion_reenvio_cooldown_segundos),
            )
            if cooldown > 0:
                response.headers["Retry-After"] = str(cooldown)
    except OperadorNoEncontradoError:
        _error_operador_no_encontrado()
    except SQLAlchemyError:
        _error_interno()
    return RespuestaOperador.model_validate(operador)


@router.post(
    "/{operador_id}/desactivar",
    response_model=RespuestaAccionOperador,
)
def desactivar_operador_endpoint(
    operador_id: int,
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAccionOperador:
    """Desactiva la cuenta y revoca sus sesiones existentes."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        desactivar_operador(db, operador_id)
    except OperadorNoEncontradoError:
        _error_operador_no_encontrado()
    except OperadorYaInactivoError:
        _error_operador_ya_inactivo()
    except SQLAlchemyError:
        _error_interno()
    return RespuestaAccionOperador(estado="operador_desactivado")


@router.post(
    "/{operador_id}/reactivar",
    response_model=RespuestaAccionOperador,
)
def reactivar_operador_endpoint(
    operador_id: int,
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAccionOperador:
    """Reactiva la cuenta sin restaurar sesiones anteriores."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        reactivar_operador(db, operador_id)
    except OperadorNoEncontradoError:
        _error_operador_no_encontrado()
    except OperadorYaActivoError:
        _error_operador_ya_activo()
    except SQLAlchemyError:
        _error_interno()
    return RespuestaAccionOperador(estado="operador_reactivado")


@router.post(
    "/{operador_id}/regenerar-contrasena",
    response_model=RespuestaAccionOperador,
)
def regenerar_contrasena_operador_endpoint(
    operador_id: int,
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAccionOperador:
    """Regenera, persiste y entrega una contraseña sin devolverla por API."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        settings = get_settings()
        transporte = crear_transporte_correo(settings)

        def entregar_credencial(usuario: Usuario, contrasena: str) -> None:
            mensaje = construir_mensaje_regeneracion_credenciales_operador(
                usuario,
                contrasena,
                settings=settings,
            )
            transporte.enviar(mensaje)

        regenerar_contrasena_operador(
            db,
            operador_id,
            entregar_credencial=entregar_credencial,
        )
    except OperadorNoEncontradoError:
        _error_operador_no_encontrado()
    except OperadorNoPuedeRegenerarContrasenaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta no tiene acceso activo para regenerar la contraseña.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except ErrorCorreo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de correo temporalmente no disponible",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        _error_interno()
    return RespuestaAccionOperador(estado="contrasena_regenerada")


@router.post(
    "/{operador_id}/reenviar-invitacion",
    response_model=RespuestaAccionOperador,
)
def reenviar_invitacion_operador_endpoint(
    operador_id: int,
    response: Response,
    _admin: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAccionOperador:
    """Entrega un enlace nuevo solo para una cuenta OPERADOR pendiente."""

    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    transporte = crear_transporte_correo(settings)

    def entregar_invitacion(usuario: Usuario, token: str) -> None:
        transporte.enviar(
            construir_mensaje_invitacion_operador(
                usuario,
                token,
                settings=settings,
            )
        )

    try:
        reenviar_invitacion_operador(
            db,
            operador_id,
            cooldown_segundos=settings.activacion_reenvio_cooldown_segundos,
            duracion_token_horas=settings.activation_token_ttl_hours,
            entregar_invitacion=entregar_invitacion,
        )
    except OperadorNoEncontradoError:
        _error_operador_no_encontrado()
    except OperadorNoPendienteError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta no está pendiente de activación.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except CooldownReenvioInvitacionError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Espera antes de reenviar la invitación.",
            headers={**CABECERA_NO_CACHE, "Retry-After": str(error.segundos_restantes)},
        ) from None
    except ErrorCorreo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de correo temporalmente no disponible",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        _error_interno()
    response.headers["Retry-After"] = str(
        settings.activacion_reenvio_cooldown_segundos
    )
    return RespuestaAccionOperador(estado="invitacion_enviada")


@router.post(
    "",
    response_model=RespuestaCrearOperador,
    status_code=status.HTTP_201_CREATED,
)
def crear_operador_endpoint(
    solicitud: SolicitudCrearOperador,
    response: Response,
    admin_usuario_id: Annotated[int, Depends(_exigir_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaCrearOperador:
    """Crea un OPERADOR autenticado y devuelve un estado sin credenciales."""

    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    transporte = crear_transporte_correo(settings)

    def entregar_invitacion(usuario: Usuario, token: str) -> None:
        mensaje = construir_mensaje_invitacion_operador(
            usuario,
            token,
            settings=settings,
        )
        transporte.enviar(mensaje)

    try:
        crear_operador(
            db,
            nombre=solicitud.nombre,
            apellido_paterno=solicitud.apellido_paterno,
            apellido_materno=solicitud.apellido_materno,
            correo=solicitud.correo,
            creado_por_usuario_id=admin_usuario_id,
            entregar_invitacion=entregar_invitacion,
            duracion_token_horas=settings.activation_token_ttl_hours,
        )
    except CorreoOperadorDuplicadoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El correo ya esta registrado.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except CorreoInvalidoError, DatoOperadorInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Solicitud invalida",
            headers=CABECERA_NO_CACHE,
        ) from None
    except ErrorCorreo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de correo temporalmente no disponible",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    return RespuestaCrearOperador(estado="operador_creado")


__all__ = ["RUTA_CREAR_OPERADOR", "router"]
