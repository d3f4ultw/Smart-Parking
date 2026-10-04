"""Consultas y cambios transaccionales para cuentas OPERADOR."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.correo.errores import ErrorCorreo
from app.models import ActivacionCuenta, RolUsuario, Usuario
from app.seguridad.activaciones import generar_token_activacion, hash_token_activacion
from app.seguridad.contrasenas import (
    crear_hash_contrasena,
    generar_contrasena_operador,
)
from app.servicios.autenticacion import revocar_sesiones_usuario
from app.servicios.eventos_operadores import registrar_evento_operador


class ErrorGestionOperador(ValueError):
    """Clase base para errores esperados de gestion de OPERADOR."""


class OperadorNoEncontradoError(ErrorGestionOperador):
    """Indica que el id solicitado no corresponde a un OPERADOR."""


class OperadorYaInactivoError(ErrorGestionOperador):
    """Indica que el OPERADOR ya esta desactivado."""


class OperadorYaActivoError(ErrorGestionOperador):
    """Indica que el OPERADOR ya esta activo."""


class OperadorNoPendienteError(ErrorGestionOperador):
    """Indica que una accion solo admite OPERADORES pendientes de activacion."""


class CooldownReenvioInvitacionError(ErrorGestionOperador):
    """Indica que el reenvio de invitacion aun esta dentro del cooldown."""

    def __init__(self, segundos_restantes: int) -> None:
        self.segundos_restantes = max(1, segundos_restantes)
        super().__init__("El reenvio de invitacion aun esta en cooldown.")


class OperadorNoPuedeRegenerarContrasenaError(ErrorGestionOperador):
    """Indica que la cuenta no tiene acceso activo para regenerar contrasena."""


EstadoCuentaOperador = Literal[
    "pendiente_activacion",
    "acceso_habilitado",
    "inactivo",
]


@dataclass(frozen=True, slots=True)
class CreadorOperadorDTO:
    """Campos de identidad permitidos para atribuir una creacion."""

    id: int
    nombre: str | None
    apellido_paterno: str | None
    apellido_materno: str | None
    correo: str


@dataclass(frozen=True, slots=True)
class OperadorDTO:
    """Datos administrativos permitidos para mostrar un OPERADOR."""

    id: int
    nombre: str
    apellido_paterno: str
    apellido_materno: str
    correo: str
    esta_activo: bool
    creado_en: datetime
    creado_por: CreadorOperadorDTO | None
    estado_cuenta: EstadoCuentaOperador


@dataclass(frozen=True, slots=True)
class ResultadoListaOperadores:
    """Pagina efectiva y conteo de cuentas OPERADOR."""

    operadores: list[OperadorDTO]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int


TAMANO_PAGINA_OPERADORES = 10


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha de gestion debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def _crear_dto(usuario: Usuario) -> OperadorDTO:
    if not usuario.esta_activo:
        estado_cuenta: EstadoCuentaOperador = "inactivo"
    elif usuario.correo_verificado and usuario.contrasena_hash is not None:
        estado_cuenta = "acceso_habilitado"
    else:
        estado_cuenta = "pendiente_activacion"

    creador = usuario.creado_por
    return OperadorDTO(
        id=usuario.id,
        nombre=usuario.nombre or "",
        apellido_paterno=usuario.apellido_paterno or "",
        apellido_materno=usuario.apellido_materno or "",
        correo=usuario.correo,
        esta_activo=usuario.esta_activo,
        creado_en=usuario.creado_en,
        creado_por=(
            CreadorOperadorDTO(
                id=creador.id,
                nombre=creador.nombre,
                apellido_paterno=creador.apellido_paterno,
                apellido_materno=creador.apellido_materno,
                correo=creador.correo,
            )
            if creador is not None
            else None
        ),
        estado_cuenta=estado_cuenta,
    )


def listar_operadores(db: Session, pagina: int) -> ResultadoListaOperadores:
    """Lista una pagina de OPERADOR con orden y conteo consistentes."""

    filtro_operadores = Usuario.rol == RolUsuario.OPERADOR.value
    total = (
        db.scalar(select(func.count()).select_from(Usuario).where(filtro_operadores))
        or 0
    )
    total_paginas = (total + TAMANO_PAGINA_OPERADORES - 1) // TAMANO_PAGINA_OPERADORES
    pagina_efectiva = min(pagina, total_paginas) if total_paginas else 1
    usuarios = db.scalars(
        select(Usuario)
        .where(filtro_operadores)
        .options(selectinload(Usuario.creado_por))
        .order_by(Usuario.id)
        .limit(TAMANO_PAGINA_OPERADORES)
        .offset((pagina_efectiva - 1) * TAMANO_PAGINA_OPERADORES)
    ).all()
    return ResultadoListaOperadores(
        operadores=[_crear_dto(usuario) for usuario in usuarios],
        pagina=pagina_efectiva,
        tamano_pagina=TAMANO_PAGINA_OPERADORES,
        total=total,
        total_paginas=total_paginas,
    )


def obtener_operador(db: Session, operador_id: int) -> OperadorDTO:
    """Obtiene un OPERADOR por id sin exponer campos internos."""

    usuario = db.scalar(
        select(Usuario).where(
            Usuario.id == operador_id,
            Usuario.rol == RolUsuario.OPERADOR.value,
        ).options(selectinload(Usuario.creado_por))
    )
    if usuario is None:
        raise OperadorNoEncontradoError
    return _crear_dto(usuario)


def _bloquear_operador(db: Session, operador_id: int) -> Usuario:
    usuario = db.scalar(
        select(Usuario)
        .where(
            Usuario.id == operador_id,
            Usuario.rol == RolUsuario.OPERADOR.value,
        )
        .with_for_update()
        # El mismo Session puede abrir otra transaccion con la fila ya cargada.
        .execution_options(populate_existing=True)
    )
    if usuario is None:
        raise OperadorNoEncontradoError
    return usuario


def desactivar_operador(
    db: Session,
    operador_id: int,
    *,
    ahora: datetime | None = None,
) -> None:
    """Desactiva la cuenta y revoca sus sesiones en una sola transaccion."""

    ahora_utc = _ahora_utc(ahora)
    try:
        with db.begin():
            usuario = _bloquear_operador(db, operador_id)
            if not usuario.esta_activo:
                raise OperadorYaInactivoError
            usuario.esta_activo = False
            if usuario.contrasena_hash is None and not usuario.correo_verificado:
                activaciones = db.scalars(
                    select(ActivacionCuenta)
                    .where(
                        ActivacionCuenta.usuario_id == usuario.id,
                        ActivacionCuenta.consumido_en.is_(None),
                    )
                    .with_for_update()
                ).all()
                for activacion in activaciones:
                    activacion.consumido_en = ahora_utc
                    activacion.desafio_hash = None
                    activacion.desafio_expira_en = None
            revocar_sesiones_usuario(
                db,
                usuario_id=usuario.id,
                ahora=ahora_utc,
            )
            registrar_evento_operador(db, usuario.id, "operador.actualizado")
    except SQLAlchemyError:
        db.rollback()
        raise


def reactivar_operador(
    db: Session,
    operador_id: int,
) -> None:
    """Reactiva la cuenta sin modificar contrasena, verificacion o sesiones."""

    try:
        with db.begin():
            usuario = _bloquear_operador(db, operador_id)
            if usuario.esta_activo:
                raise OperadorYaActivoError
            usuario.esta_activo = True
            registrar_evento_operador(db, usuario.id, "operador.actualizado")
    except SQLAlchemyError:
        db.rollback()
        raise


def regenerar_contrasena_operador(
    db: Session,
    operador_id: int,
    *,
    entregar_credencial: Callable[[Usuario, str], None],
    ahora: datetime | None = None,
) -> None:
    """Reemplaza el hash, revoca sesiones y entrega la credencial efimera."""

    credencial_generada = generar_contrasena_operador()
    try:
        contrasena_hash = crear_hash_contrasena(credencial_generada)
        ahora_utc = _ahora_utc(ahora)
        try:
            with db.begin():
                usuario = _bloquear_operador(db, operador_id)
                if (
                    not usuario.esta_activo
                    or not usuario.correo_verificado
                    or usuario.contrasena_hash is None
                ):
                    raise OperadorNoPuedeRegenerarContrasenaError
                usuario.contrasena_hash = contrasena_hash
                revocar_sesiones_usuario(
                    db,
                    usuario_id=usuario.id,
                    ahora=ahora_utc,
                )
                db.flush()
                entregar_credencial(usuario, credencial_generada)
        except ErrorCorreo:
            db.rollback()
            raise
        except SQLAlchemyError:
            db.rollback()
            raise
    finally:
        del credencial_generada


def _fecha_utc(fecha: datetime) -> datetime:
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        return fecha.replace(tzinfo=UTC)
    return fecha.astimezone(UTC)


def _cooldown_invitacion_activo(
    activacion: ActivacionCuenta,
    *,
    cooldown_segundos: int,
    ahora_utc: datetime,
) -> int:
    ultima_fecha = _fecha_utc(activacion.creado_en)
    if activacion.ultimo_reenvio_en is not None:
        ultima_fecha = max(ultima_fecha, _fecha_utc(activacion.ultimo_reenvio_en))
    restante = ceil(
        (
            ultima_fecha + timedelta(seconds=cooldown_segundos) - ahora_utc
        ).total_seconds()
    )
    return max(0, restante)


def obtener_cooldown_reenvio_operador(
    db: Session,
    operador_id: int,
    *,
    cooldown_segundos: int,
    ahora: datetime | None = None,
) -> int:
    """Calcula el cooldown vigente desde la ultima activacion registrada."""

    if cooldown_segundos <= 0:
        raise ValueError("La configuracion de reenvio no es valida.")

    activacion = db.scalar(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador_id)
        .order_by(desc(ActivacionCuenta.creado_en), desc(ActivacionCuenta.id))
        .limit(1)
    )
    if activacion is None:
        return 0

    return _cooldown_invitacion_activo(
        activacion,
        cooldown_segundos=cooldown_segundos,
        ahora_utc=_ahora_utc(ahora),
    )


def _operador_pendiente_activo(usuario: Usuario) -> bool:
    return (
        usuario.rol == RolUsuario.OPERADOR.value
        and usuario.esta_activo
        and not usuario.correo_verificado
        and usuario.contrasena_hash is None
    )


def reenviar_invitacion_operador(
    db: Session,
    operador_id: int,
    *,
    cooldown_segundos: int,
    duracion_token_horas: int,
    entregar_invitacion: Callable[[Usuario, str], None],
    ahora: datetime | None = None,
) -> None:
    """Reserva cooldown, entrega enlace y reemplaza solo la invitacion vigente."""

    if cooldown_segundos <= 0 or not 1 <= duracion_token_horas <= 168:
        raise ValueError("La configuracion de reenvio no es valida.")
    ahora_utc = _ahora_utc(ahora)
    token = generar_token_activacion()
    invitacion_consumida_al_reservar = False
    activacion_id: int

    try:
        with db.begin():
            usuario = _bloquear_operador(db, operador_id)
            if not _operador_pendiente_activo(usuario):
                raise OperadorNoPendienteError

            ultima_activacion = db.scalar(
                select(ActivacionCuenta)
                .where(ActivacionCuenta.usuario_id == usuario.id)
                .order_by(desc(ActivacionCuenta.creado_en), desc(ActivacionCuenta.id))
                .limit(1)
                .with_for_update()
            )
            if ultima_activacion is None:
                ultima_activacion = ActivacionCuenta(
                    usuario_id=usuario.id,
                    token_hash=hash_token_activacion(token),
                    codigo_hash=None,
                    expira_en=ahora_utc + timedelta(hours=duracion_token_horas),
                    creado_en=ahora_utc,
                    ultimo_reenvio_en=ahora_utc,
                )
                db.add(ultima_activacion)
                db.flush()
            else:
                invitacion_consumida_al_reservar = (
                    ultima_activacion.consumido_en is not None
                )
                segundos_restantes = _cooldown_invitacion_activo(
                    ultima_activacion,
                    cooldown_segundos=cooldown_segundos,
                    ahora_utc=ahora_utc,
                )
                if segundos_restantes:
                    raise CooldownReenvioInvitacionError(segundos_restantes)
                ultima_activacion.ultimo_reenvio_en = ahora_utc

            activacion_id = ultima_activacion.id
    except CooldownReenvioInvitacionError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise

    try:
        entregar_invitacion(usuario, token)

        with db.begin():
            usuario_bloqueado = _bloquear_operador(db, operador_id)
            if not _operador_pendiente_activo(usuario_bloqueado):
                raise OperadorNoPendienteError

            activacion_actual = db.scalar(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.id == activacion_id,
                    ActivacionCuenta.usuario_id == usuario_bloqueado.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            ultima_actual = db.scalar(
                select(ActivacionCuenta)
                .where(ActivacionCuenta.usuario_id == usuario_bloqueado.id)
                .order_by(desc(ActivacionCuenta.creado_en), desc(ActivacionCuenta.id))
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                activacion_actual is None
                or ultima_actual is None
                or ultima_actual.id != activacion_id
                or (
                    activacion_actual.consumido_en is not None
                    and not invitacion_consumida_al_reservar
                )
                or activacion_actual.ultimo_reenvio_en is None
                or _fecha_utc(activacion_actual.ultimo_reenvio_en) != ahora_utc
            ):
                raise OperadorNoPendienteError

            if activacion_actual.token_hash != hash_token_activacion(token):
                activaciones_pendientes = db.scalars(
                    select(ActivacionCuenta)
                    .where(
                        ActivacionCuenta.usuario_id == usuario_bloqueado.id,
                        ActivacionCuenta.consumido_en.is_(None),
                    )
                    .with_for_update()
                    # La reserva previa puede conservar una fila desactualizada.
                    .execution_options(populate_existing=True)
                ).all()
                for activacion in activaciones_pendientes:
                    activacion.consumido_en = ahora_utc
                    activacion.desafio_hash = None
                    activacion.desafio_expira_en = None

                db.add(
                    ActivacionCuenta(
                        usuario_id=usuario_bloqueado.id,
                        token_hash=hash_token_activacion(token),
                        codigo_hash=None,
                        expira_en=ahora_utc + timedelta(hours=duracion_token_horas),
                        creado_en=ahora_utc,
                        ultimo_reenvio_en=ahora_utc,
                    )
                )
    finally:
        del token


__all__ = [
    "ErrorGestionOperador",
    "CooldownReenvioInvitacionError",
    "OperadorDTO",
    "OperadorNoPuedeRegenerarContrasenaError",
    "OperadorNoEncontradoError",
    "OperadorNoPendienteError",
    "OperadorYaActivoError",
    "OperadorYaInactivoError",
    "ResultadoListaOperadores",
    "TAMANO_PAGINA_OPERADORES",
    "desactivar_operador",
    "listar_operadores",
    "obtener_operador",
    "reactivar_operador",
    "reenviar_invitacion_operador",
    "regenerar_contrasena_operador",
]
