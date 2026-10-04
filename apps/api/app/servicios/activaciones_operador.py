"""Flujo compartido de enlace y desafio para activar cuentas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import ActivacionCuenta, RolUsuario, Usuario
from app.seguridad.activaciones import generar_token_activacion, hash_token_activacion
from app.seguridad.contrasenas import (
    ContrasenaInvalidaError,
    crear_hash_contrasena,
    validar_contrasena,
)
from app.servicios.autenticacion import revocar_sesiones_usuario
from app.servicios.eventos_operadores import registrar_evento_operador


class ActivacionOperadorNoDisponible(ValueError):
    """Indica que el enlace, cuenta o desafio ya no es utilizable."""


@dataclass(frozen=True, slots=True)
class ResultadoDesafioOperador:
    """Desafio creado; el valor original solo se entrega mediante cookie."""

    token: str = field(repr=False)


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha de activacion debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def _cuenta_pendiente_activa(usuario: Usuario) -> bool:
    if not usuario.esta_activo or usuario.correo_verificado:
        return False
    if usuario.rol == RolUsuario.ADMIN.value:
        # ADMIN legacy puede tener un hash previo; el enlace aceptado establece
        # una contraseña nueva antes de habilitar el acceso.
        return True
    return usuario.rol == RolUsuario.OPERADOR.value and usuario.contrasena_hash is None


def _ultima_activacion_id(db: Session, usuario_id: int) -> int | None:
    return db.scalar(
        select(ActivacionCuenta.id)
        .where(ActivacionCuenta.usuario_id == usuario_id)
        .order_by(desc(ActivacionCuenta.creado_en), desc(ActivacionCuenta.id))
        .limit(1)
    )


def _obtener_fila_por_hash(
    db: Session,
    *,
    condicion: ColumnElement[bool],
) -> tuple[int, int] | None:
    consulta = select(ActivacionCuenta.id, ActivacionCuenta.usuario_id).where(condicion)
    resultado = db.execute(consulta).one_or_none()
    if resultado is None:
        return None
    return resultado.id, resultado.usuario_id


def _estado_desafio_valido(
    db: Session,
    usuario: Usuario | None,
    activacion: ActivacionCuenta | None,
    *,
    ahora_utc: datetime,
    hash_desafio: str,
) -> bool:
    if (
        usuario is None
        or activacion is None
        or not _cuenta_pendiente_activa(usuario)
        or activacion.codigo_hash is not None
        or activacion.consumido_en is not None
        or activacion.expira_en <= ahora_utc
        or activacion.desafio_hash != hash_desafio
        or activacion.desafio_expira_en is None
        or activacion.desafio_expira_en <= ahora_utc
    ):
        return False
    return _ultima_activacion_id(db, usuario.id) == activacion.id


def canjear_enlace_operador(
    db: Session,
    *,
    token: str,
    duracion_desafio_minutos: int,
    ahora: datetime | None = None,
) -> ResultadoDesafioOperador:
    """Canjea un enlace actual por un desafio hash-only de corta duracion."""

    if not 5 <= duracion_desafio_minutos <= 60:
        raise ValueError("La vigencia del desafio no es valida.")
    hash_token = hash_token_activacion(token)
    ahora_utc = _ahora_utc(ahora)
    try:
        with db.begin():
            referencia = _obtener_fila_por_hash(
                db,
                condicion=ActivacionCuenta.token_hash == hash_token,
            )
            if referencia is None:
                raise ActivacionOperadorNoDisponible

            activacion_id, usuario_id = referencia
            usuario = db.scalar(
                select(Usuario).where(Usuario.id == usuario_id).with_for_update()
            )
            activacion = db.scalar(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.id == activacion_id,
                    ActivacionCuenta.usuario_id == usuario_id,
                    ActivacionCuenta.token_hash == hash_token,
                )
                .with_for_update()
            )
            if (
                usuario is None
                or activacion is None
                or not _cuenta_pendiente_activa(usuario)
                or activacion.codigo_hash is not None
                or activacion.consumido_en is not None
                or activacion.expira_en <= ahora_utc
                or _ultima_activacion_id(db, usuario.id) != activacion.id
            ):
                raise ActivacionOperadorNoDisponible

            token_desafio = generar_token_activacion()
            activacion.desafio_hash = hash_token_activacion(token_desafio)
            activacion.desafio_expira_en = ahora_utc + timedelta(
                minutes=duracion_desafio_minutos
            )
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoDesafioOperador(token=token_desafio)


def verificar_desafio_operador(
    db: Session,
    *,
    token_desafio: str | None,
    ahora: datetime | None = None,
) -> bool:
    """Indica si una cookie representa el desafio actual sin revelar la cuenta."""

    if not token_desafio:
        db.rollback()
        return False

    hash_desafio = hash_token_activacion(token_desafio)
    ahora_utc = _ahora_utc(ahora)
    referencia = _obtener_fila_por_hash(
        db,
        condicion=ActivacionCuenta.desafio_hash == hash_desafio,
    )
    if referencia is None:
        db.rollback()
        return False

    activacion_id, usuario_id = referencia
    activacion = db.get(ActivacionCuenta, activacion_id)
    usuario = db.get(Usuario, usuario_id)
    valido = _estado_desafio_valido(
        db,
        usuario,
        activacion,
        ahora_utc=ahora_utc,
        hash_desafio=hash_desafio,
    )
    db.rollback()
    return valido


def completar_activacion_operador(
    db: Session,
    *,
    token_desafio: str | None,
    nueva_contrasena: str,
    ahora: datetime | None = None,
) -> None:
    """Establece la primera contrasena y consume la invitacion atomicamente."""

    if not token_desafio:
        db.rollback()
        raise ActivacionOperadorNoDisponible

    hash_desafio = hash_token_activacion(token_desafio)
    try:
        with db.begin():
            referencia = _obtener_fila_por_hash(
                db,
                condicion=ActivacionCuenta.desafio_hash == hash_desafio,
            )
            if referencia is None:
                raise ActivacionOperadorNoDisponible

            activacion_id, usuario_id = referencia
            usuario = db.scalar(
                select(Usuario).where(Usuario.id == usuario_id).with_for_update()
            )
            activacion = db.scalar(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.id == activacion_id,
                    ActivacionCuenta.usuario_id == usuario_id,
                    ActivacionCuenta.desafio_hash == hash_desafio,
                )
                .with_for_update()
            )
            ahora_inicio = _ahora_utc(ahora)
            if not _estado_desafio_valido(
                db,
                usuario,
                activacion,
                ahora_utc=ahora_inicio,
                hash_desafio=hash_desafio,
            ):
                raise ActivacionOperadorNoDisponible

            validar_contrasena(nueva_contrasena)
            contrasena_hash = crear_hash_contrasena(nueva_contrasena)

            ahora_commit = _ahora_utc(ahora) if ahora is not None else datetime.now(UTC)
            if not _estado_desafio_valido(
                db,
                usuario,
                activacion,
                ahora_utc=ahora_commit,
                hash_desafio=hash_desafio,
            ):
                raise ActivacionOperadorNoDisponible

            assert usuario is not None
            assert activacion is not None
            usuario.contrasena_hash = contrasena_hash
            usuario.correo_verificado = True
            usuario.debe_cambiar_contrasena = False
            activacion.consumido_en = ahora_commit
            activacion.desafio_hash = None
            activacion.desafio_expira_en = None
            revocar_sesiones_usuario(
                db,
                usuario_id=usuario.id,
                ahora=ahora_commit,
            )
            if usuario.rol == RolUsuario.OPERADOR.value:
                registrar_evento_operador(db, usuario.id, "operador.actualizado")
    except ActivacionOperadorNoDisponible, ContrasenaInvalidaError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "ActivacionOperadorNoDisponible",
    "ResultadoDesafioOperador",
    "canjear_enlace_operador",
    "completar_activacion_operador",
    "verificar_desafio_operador",
]
