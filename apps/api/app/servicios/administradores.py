"""Consultas y cambios atomicos para la gestion de ADMIN existentes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import ActivacionCuenta, RolUsuario, Usuario
from app.seguridad.activaciones import generar_token_activacion, hash_token_activacion
from app.seguridad.correos import normalizar_correo
from app.servicios.autenticacion import revocar_sesiones_vigentes

EstadoActivacion = Literal[
    "No requerida",
    "Pendiente",
    "Sin activación vigente",
    "Pendiente; cuenta inactiva",
]
ModoActivacion = Literal["Enlace", "Manual", "Temporal"]


class ErrorGestionAdministrador(ValueError):
    """Clase base para errores esperados de la gestion de ADMIN."""


class AdministradorNoEncontradoError(ErrorGestionAdministrador):
    """Indica que el identificador no corresponde a un ADMIN."""

    def __init__(self) -> None:
        super().__init__("No se encontro el ADMIN solicitado.")


class AdministradorYaInactivoError(ErrorGestionAdministrador):
    """Indica que no es necesario repetir una desactivacion."""

    def __init__(self) -> None:
        super().__init__("El ADMIN ya esta inactivo.")


class AdministradorYaActivoError(ErrorGestionAdministrador):
    """Indica que no es necesario repetir una reactivacion."""

    def __init__(self) -> None:
        super().__init__("El ADMIN ya esta activo.")


class AdministradorNoPendienteError(ErrorGestionAdministrador):
    """Indica que el ADMIN ya no puede recibir una invitacion."""


class CooldownReenvioAdministradorError(ErrorGestionAdministrador):
    """Indica el tiempo restante antes de reenviar otra invitacion ADMIN."""

    def __init__(self, segundos_restantes: int) -> None:
        self.segundos_restantes = max(1, segundos_restantes)
        super().__init__("El reenvio de invitacion aun esta en cooldown.")


@dataclass(frozen=True, slots=True)
class AdministradorDTO:
    """Vista segura de un ADMIN, sin hashes, tokens ni contrasenas."""

    id: int
    nombre: str
    apellido_paterno: str
    apellido_materno: str
    correo: str
    esta_activo: bool
    correo_verificado: bool
    debe_cambiar_contrasena: bool
    estado_activacion: EstadoActivacion
    modo_activacion: ModoActivacion | None


AdministradorResumen = AdministradorDTO
AdministradorDetalle = AdministradorDTO


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha de gestion debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def _fecha_utc(fecha: datetime) -> datetime:
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        return fecha.replace(tzinfo=UTC)
    return fecha.astimezone(UTC)


def _obtener_usuarios_admin(
    db: Session,
    *,
    condicion: ColumnElement[bool] | None = None,
    ordenados: bool = False,
) -> list[Usuario]:
    consulta = select(Usuario).where(Usuario.rol == RolUsuario.ADMIN.value)
    if condicion is not None:
        consulta = consulta.where(condicion)
    if ordenados:
        consulta = consulta.order_by(Usuario.id)
    return list(db.scalars(consulta).all())


def _usuarios_con_activacion_pendiente(
    db: Session,
    usuarios: list[Usuario],
    *,
    ahora_utc: datetime,
) -> set[int]:
    """Obtiene el estado de activacion con una consulta adicional, no N+1."""

    ids = [usuario.id for usuario in usuarios]
    if not ids:
        return set()

    pendientes: set[int] = set()
    filas = db.execute(
        select(
            ActivacionCuenta.usuario_id,
            ActivacionCuenta.expira_en,
            ActivacionCuenta.consumido_en,
        ).where(ActivacionCuenta.usuario_id.in_(ids))
    )
    for usuario_id, expira_en, consumido_en in filas:
        if consumido_en is None and _fecha_utc(expira_en) > ahora_utc:
            pendientes.add(usuario_id)
    return pendientes


def _crear_dto(usuario: Usuario, pendientes: set[int]) -> AdministradorDTO:
    if usuario.correo_verificado:
        estado_activacion: EstadoActivacion = "No requerida"
        modo_activacion: ModoActivacion | None = None
    else:
        if usuario.contrasena_hash is None:
            modo_activacion = "Enlace"
        else:
            modo_activacion = (
                "Temporal" if usuario.debe_cambiar_contrasena else "Manual"
            )
        if usuario.id in pendientes:
            estado_activacion = (
                "Pendiente" if usuario.esta_activo else "Pendiente; cuenta inactiva"
            )
        else:
            estado_activacion = "Sin activación vigente"

    return AdministradorDTO(
        id=usuario.id,
        nombre=usuario.nombre or "",
        apellido_paterno=usuario.apellido_paterno or "",
        apellido_materno=usuario.apellido_materno or "",
        correo=usuario.correo,
        esta_activo=usuario.esta_activo,
        correo_verificado=usuario.correo_verificado,
        debe_cambiar_contrasena=usuario.debe_cambiar_contrasena,
        estado_activacion=estado_activacion,
        modo_activacion=modo_activacion,
    )


def _crear_dtos(
    db: Session,
    usuarios: list[Usuario],
    *,
    ahora: datetime | None,
) -> list[AdministradorDTO]:
    ahora_utc = _ahora_utc(ahora)
    pendientes = _usuarios_con_activacion_pendiente(
        db,
        usuarios,
        ahora_utc=ahora_utc,
    )
    return [_crear_dto(usuario, pendientes) for usuario in usuarios]


def listar_administradores(
    db: Session,
    *,
    ahora: datetime | None = None,
) -> list[AdministradorResumen]:
    """Lista solamente ADMIN, en orden ascendente y con DTOs seguros."""

    usuarios = _obtener_usuarios_admin(db, ordenados=True)
    return _crear_dtos(db, usuarios, ahora=ahora)


def buscar_administrador_por_id(
    db: Session,
    administrador_id: int,
    *,
    ahora: datetime | None = None,
) -> AdministradorDetalle | None:
    """Busca un ADMIN por identificador exacto."""

    if administrador_id <= 0:
        return None
    usuarios = _obtener_usuarios_admin(
        db,
        condicion=Usuario.id == administrador_id,
    )
    return _crear_dtos(db, usuarios, ahora=ahora)[0] if usuarios else None


def buscar_administrador_por_correo(
    db: Session,
    correo: str,
    *,
    ahora: datetime | None = None,
) -> AdministradorDetalle | None:
    """Busca un ADMIN por correo normalizado y exacto."""

    correo_normalizado = normalizar_correo(correo)
    usuarios = _obtener_usuarios_admin(
        db,
        condicion=Usuario.correo == correo_normalizado,
    )
    return _crear_dtos(db, usuarios, ahora=ahora)[0] if usuarios else None


def obtener_administrador(
    db: Session,
    administrador_id: int,
    *,
    ahora: datetime | None = None,
) -> AdministradorDetalle:
    """Obtiene un detalle seguro o informa que el ADMIN ya no existe."""

    administrador = buscar_administrador_por_id(
        db,
        administrador_id,
        ahora=ahora,
    )
    if administrador is None:
        raise AdministradorNoEncontradoError
    return administrador


def _bloquear_administrador(db: Session, administrador_id: int) -> Usuario:
    usuario = db.scalar(
        select(Usuario)
        .where(
            Usuario.id == administrador_id,
            Usuario.rol == RolUsuario.ADMIN.value,
        )
        .with_for_update()
    )
    if usuario is None:
        raise AdministradorNoEncontradoError
    return usuario


def _administrador_pendiente_activo(usuario: Usuario) -> bool:
    """Acepta ADMIN no verificado, incluidos registros legacy con hash."""

    return (
        usuario.rol == RolUsuario.ADMIN.value
        and usuario.esta_activo
        and not usuario.correo_verificado
    )


def _cooldown_invitacion_activo(
    activacion: ActivacionCuenta,
    *,
    cooldown_segundos: int,
    ahora_utc: datetime,
) -> int:
    ultima_fecha = _fecha_utc(activacion.creado_en)
    if activacion.ultimo_reenvio_en is not None:
        ultima_fecha = max(ultima_fecha, _fecha_utc(activacion.ultimo_reenvio_en))
    return max(
        0,
        ceil(
            (
                ultima_fecha + timedelta(seconds=cooldown_segundos) - ahora_utc
            ).total_seconds()
        ),
    )


def reenviar_invitacion_administrador(
    db: Session,
    administrador_id: int,
    *,
    cooldown_segundos: int,
    duracion_token_horas: int,
    entregar_invitacion: Callable[[Usuario, str], None],
    ahora: datetime | None = None,
) -> None:
    """Entrega primero y rota luego la invitacion pendiente token-only."""

    if cooldown_segundos <= 0 or not 1 <= duracion_token_horas <= 168:
        raise ValueError("La configuracion de reenvio no es valida.")
    ahora_utc = _ahora_utc(ahora)
    token = generar_token_activacion()
    invitacion_consumida_al_reservar = False
    activacion_id: int

    try:
        with db.begin():
            usuario = _bloquear_administrador(db, administrador_id)
            if not _administrador_pendiente_activo(usuario):
                raise AdministradorNoPendienteError

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
                    raise CooldownReenvioAdministradorError(segundos_restantes)
                ultima_activacion.ultimo_reenvio_en = ahora_utc

            activacion_id = ultima_activacion.id
    except AdministradorNoEncontradoError, AdministradorNoPendienteError:
        db.rollback()
        raise
    except CooldownReenvioAdministradorError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise

    try:
        entregar_invitacion(usuario, token)

        with db.begin():
            usuario_bloqueado = _bloquear_administrador(db, administrador_id)
            if not _administrador_pendiente_activo(usuario_bloqueado):
                raise AdministradorNoPendienteError

            activacion_actual = db.scalar(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.id == activacion_id,
                    ActivacionCuenta.usuario_id == usuario_bloqueado.id,
                )
                .with_for_update()
            )
            ultima_actual = db.scalar(
                select(ActivacionCuenta)
                .where(ActivacionCuenta.usuario_id == usuario_bloqueado.id)
                .order_by(desc(ActivacionCuenta.creado_en), desc(ActivacionCuenta.id))
                .limit(1)
                .with_for_update()
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
                raise AdministradorNoPendienteError

            if activacion_actual.token_hash != hash_token_activacion(token):
                activaciones_pendientes = db.scalars(
                    select(ActivacionCuenta)
                    .where(
                        ActivacionCuenta.usuario_id == usuario_bloqueado.id,
                        ActivacionCuenta.consumido_en.is_(None),
                    )
                    .with_for_update()
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
    except AdministradorNoEncontradoError, AdministradorNoPendienteError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        del token


def desactivar_administrador(
    db: Session,
    administrador_id: int,
    *,
    ahora: datetime | None = None,
) -> None:
    """Desactiva un ADMIN y revoca sus sesiones vigentes de forma atomica."""

    ahora_utc = _ahora_utc(ahora)
    try:
        with db.begin():
            usuario = _bloquear_administrador(db, administrador_id)
            if not usuario.esta_activo:
                raise AdministradorYaInactivoError
            usuario.esta_activo = False
            activaciones_pendientes = db.scalars(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.usuario_id == usuario.id,
                    ActivacionCuenta.consumido_en.is_(None),
                )
                .with_for_update()
            ).all()
            for activacion in activaciones_pendientes:
                activacion.consumido_en = ahora_utc
                activacion.desafio_hash = None
                activacion.desafio_expira_en = None
            revocar_sesiones_vigentes(
                db,
                usuario_id=usuario.id,
                ahora=ahora_utc,
            )
    except SQLAlchemyError:
        db.rollback()
        raise


def reactivar_administrador(
    db: Session,
    administrador_id: int,
    *,
    ahora: datetime | None = None,
) -> None:
    """Reactiva un ADMIN sin alterar verificacion, contrasena ni sesiones."""

    _ahora_utc(ahora)
    try:
        with db.begin():
            usuario = _bloquear_administrador(db, administrador_id)
            if usuario.esta_activo:
                raise AdministradorYaActivoError
            usuario.esta_activo = True
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "AdministradorDetalle",
    "AdministradorDTO",
    "AdministradorNoEncontradoError",
    "AdministradorResumen",
    "AdministradorYaActivoError",
    "AdministradorYaInactivoError",
    "AdministradorNoPendienteError",
    "CooldownReenvioAdministradorError",
    "ErrorGestionAdministrador",
    "EstadoActivacion",
    "ModoActivacion",
    "buscar_administrador_por_correo",
    "buscar_administrador_por_id",
    "desactivar_administrador",
    "listar_administradores",
    "obtener_administrador",
    "reactivar_administrador",
    "reenviar_invitacion_administrador",
]
