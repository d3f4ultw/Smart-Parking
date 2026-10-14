"""Solicitud y confirmacion atomica de la desvinculacion de OWNER."""

from __future__ import annotations

import hashlib
import math
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    CuentaPropietario,
    DesvinculacionPropietario,
    RolUsuario,
    Usuario,
)
from app.seguridad.contrasenas import (
    HASH_DUMMY_CONTRASENA,
    verificar_contrasena,
)
from app.servicios.autenticacion import revocar_sesiones_usuario

VIGENCIA_CONFIRMACION_DESVINCULACION = timedelta(minutes=15)
VENTANA_SOLICITUDES_DESVINCULACION = timedelta(minutes=30)
MAXIMAS_SOLICITUDES_DESVINCULACION = 3
ROLES_ANTERIORES_VALIDOS = frozenset({None, RolUsuario.OPERADOR.value})


class PropietarioNoDisponibleError(ValueError):
    """El OWNER o su credencial administrativa no permiten el flujo."""


class ContrasenaAdministrativaIncorrectaError(ValueError):
    """La credencial administrativa independiente no coincide."""


class ConfirmacionDesvinculacionPendienteError(ValueError):
    """Ya hay un enlace de confirmacion vigente."""


class LimiteSolicitudesDesvinculacionError(ValueError):
    """Se alcanzo el limite temporal de correos de desvinculacion."""


class ConfirmacionDesvinculacionNoValidaError(ValueError):
    """El enlace no existe, vencio, fue reemplazado o ya se consumio."""


def _ahora_transaccion(db: Session, ahora: datetime | None) -> datetime:
    if ahora is not None:
        if ahora.tzinfo is None or ahora.utcoffset() is None:
            raise ValueError("La fecha de desvinculacion debe incluir zona horaria.")
        return ahora.astimezone(UTC)

    valor = db.scalar(select(func.clock_timestamp()))
    if not isinstance(valor, datetime):
        raise SQLAlchemyError("No se pudo obtener la hora de PostgreSQL.")
    if valor.tzinfo is None or valor.utcoffset() is None:
        return valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC)


def hash_token_desvinculacion(token: str) -> str:
    """Devuelve la huella SHA-256 del token, separada por proposito."""

    return hashlib.sha256(f"owner-unlink-v1:{token}".encode()).hexdigest()


def obtener_id_owner_activo(db: Session) -> int | None:
    """Consulta solo el identificador usado para limitar solicitudes."""

    return db.scalar(
        select(Usuario.id)
        .where(
            Usuario.rol == RolUsuario.OWNER.value,
            Usuario.esta_activo.is_(True),
        )
        .limit(1)
    )


def obtener_owner_activo(db: Session) -> Usuario | None:
    """Devuelve el OWNER actual para una proyeccion privada de gestion."""

    return db.scalar(
        select(Usuario)
        .where(
            Usuario.rol == RolUsuario.OWNER.value,
            Usuario.esta_activo.is_(True),
        )
        .limit(1)
    )


def obtener_segundos_desvinculacion_vigente(
    db: Session,
    *,
    usuario_id: int,
) -> int:
    """Devuelve el tiempo restante sin exponer el token del enlace."""

    instante = _ahora_transaccion(db, None)
    expira_en = db.scalar(
        select(DesvinculacionPropietario.expira_en)
        .where(
            DesvinculacionPropietario.usuario_id == usuario_id,
            DesvinculacionPropietario.consumida_en.is_(None),
            DesvinculacionPropietario.invalidada_en.is_(None),
            DesvinculacionPropietario.expira_en > instante,
        )
        .order_by(DesvinculacionPropietario.emitida_en.desc())
        .limit(1)
    )
    if expira_en is None:
        return 0

    return max(0, math.ceil((expira_en - instante).total_seconds()))


def solicitar_desvinculacion_propietario(
    db: Session,
    *,
    contrasena_admin: str,
    entregar_enlace: Callable[[str, str], None],
    ahora: datetime | None = None,
) -> None:
    """Valida la credencial separada y envia un enlace de 15 minutos."""

    db.rollback()
    error: ValueError | None = None
    correo: str | None = None
    token: str | None = None

    try:
        with db.begin():
            instante = _ahora_transaccion(db, ahora)
            usuario = db.scalar(
                select(Usuario)
                .where(
                    Usuario.rol == RolUsuario.OWNER.value,
                    Usuario.esta_activo.is_(True),
                )
                .limit(1)
                .with_for_update()
            )

            if usuario is None:
                verificar_contrasena(contrasena_admin, HASH_DUMMY_CONTRASENA)
                error = PropietarioNoDisponibleError()
            else:
                cuenta = db.scalar(
                    select(CuentaPropietario)
                    .where(CuentaPropietario.usuario_id == usuario.id)
                    .with_for_update()
                )
                hash_admin = (
                    cuenta.contrasena_admin_hash if cuenta is not None else None
                )
                if hash_admin is None:
                    verificar_contrasena(contrasena_admin, HASH_DUMMY_CONTRASENA)
                    error = PropietarioNoDisponibleError()
                elif not verificar_contrasena(contrasena_admin, hash_admin):
                    error = ContrasenaAdministrativaIncorrectaError()
                elif (
                    not usuario.correo_verificado
                    or usuario.contrasena_hash is None
                    or cuenta is None
                    or cuenta.rol_anterior not in ROLES_ANTERIORES_VALIDOS
                ):
                    error = PropietarioNoDisponibleError()
                else:
                    pendiente = db.scalar(
                        select(DesvinculacionPropietario)
                        .where(
                            DesvinculacionPropietario.usuario_id == usuario.id,
                            DesvinculacionPropietario.consumida_en.is_(None),
                            DesvinculacionPropietario.invalidada_en.is_(None),
                        )
                        .order_by(DesvinculacionPropietario.id.desc())
                        .with_for_update()
                    )
                    if pendiente is not None and pendiente.expira_en > instante:
                        error = ConfirmacionDesvinculacionPendienteError()
                    else:
                        if pendiente is not None:
                            pendiente.invalidada_en = instante

                        desde = instante - VENTANA_SOLICITUDES_DESVINCULACION
                        cantidad = (
                            db.scalar(
                                select(func.count(DesvinculacionPropietario.id)).where(
                                    DesvinculacionPropietario.usuario_id == usuario.id,
                                    DesvinculacionPropietario.emitida_en >= desde,
                                )
                            )
                            or 0
                        )
                        if cantidad >= MAXIMAS_SOLICITUDES_DESVINCULACION:
                            error = LimiteSolicitudesDesvinculacionError()
                        else:
                            token = secrets.token_urlsafe(32)
                            solicitud = DesvinculacionPropietario(
                                usuario_id=usuario.id,
                                cuenta_propietario_id=cuenta.id,
                                token_hash=hash_token_desvinculacion(token),
                                emitida_en=instante,
                                expira_en=(
                                    instante + VIGENCIA_CONFIRMACION_DESVINCULACION
                                ),
                            )
                            db.add(solicitud)
                            db.flush()
                            correo = usuario.correo
                            entregar_enlace(correo, token)
    except SQLAlchemyError:
        db.rollback()
        raise
    except Exception:
        # A transport failure must roll back the provisional token record.
        db.rollback()
        raise

    if error is not None:
        raise error


def confirmar_desvinculacion_propietario(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> None:
    """Consume el enlace y revoca sesiones dentro de la misma transaccion."""

    huella = hash_token_desvinculacion(token)
    db.rollback()
    confirmada = False

    try:
        with db.begin():
            instante = _ahora_transaccion(db, ahora)
            referencia = db.execute(
                select(
                    DesvinculacionPropietario.id,
                    DesvinculacionPropietario.usuario_id,
                    DesvinculacionPropietario.cuenta_propietario_id,
                ).where(DesvinculacionPropietario.token_hash == huella)
            ).first()

            if referencia is not None:
                # Start and confirmation both lock user, profile, then request.
                usuario = db.scalar(
                    select(Usuario)
                    .where(Usuario.id == referencia.usuario_id)
                    .with_for_update()
                )
                cuenta = db.scalar(
                    select(CuentaPropietario)
                    .where(
                        CuentaPropietario.id == referencia.cuenta_propietario_id,
                        CuentaPropietario.usuario_id == referencia.usuario_id,
                    )
                    .with_for_update()
                )
                solicitud = db.scalar(
                    select(DesvinculacionPropietario)
                    .where(DesvinculacionPropietario.id == referencia.id)
                    .with_for_update()
                )

                if (
                    solicitud is not None
                    and solicitud.token_hash == huella
                    and solicitud.consumida_en is None
                    and solicitud.invalidada_en is None
                ):
                    if solicitud.expira_en <= instante:
                        solicitud.invalidada_en = instante
                    elif (
                        usuario is not None
                        and cuenta is not None
                        and usuario.esta_activo
                        and usuario.rol == RolUsuario.OWNER.value
                        and usuario.correo_verificado
                        and usuario.contrasena_hash is not None
                        and solicitud.usuario_id == usuario.id
                        and solicitud.cuenta_propietario_id == cuenta.id
                        and cuenta.contrasena_admin_hash is not None
                        and cuenta.rol_anterior in ROLES_ANTERIORES_VALIDOS
                    ):
                        db.execute(
                            update(DesvinculacionPropietario)
                            .where(
                                DesvinculacionPropietario.usuario_id == usuario.id,
                                DesvinculacionPropietario.id != solicitud.id,
                                DesvinculacionPropietario.consumida_en.is_(None),
                                DesvinculacionPropietario.invalidada_en.is_(None),
                            )
                            .values(invalidada_en=instante)
                        )
                        usuario.rol = cuenta.rol_anterior
                        cuenta.contrasena_admin_hash = None
                        solicitud.consumida_en = instante
                        revocar_sesiones_usuario(
                            db,
                            usuario_id=usuario.id,
                            ahora=instante,
                        )
                        db.flush()
                        confirmada = True
                    else:
                        solicitud.invalidada_en = instante
    except SQLAlchemyError:
        db.rollback()
        raise

    if not confirmada:
        raise ConfirmacionDesvinculacionNoValidaError


__all__ = [
    "ConfirmacionDesvinculacionNoValidaError",
    "ConfirmacionDesvinculacionPendienteError",
    "ContrasenaAdministrativaIncorrectaError",
    "LimiteSolicitudesDesvinculacionError",
    "MAXIMAS_SOLICITUDES_DESVINCULACION",
    "PropietarioNoDisponibleError",
    "VIGENCIA_CONFIRMACION_DESVINCULACION",
    "confirmar_desvinculacion_propietario",
    "hash_token_desvinculacion",
    "obtener_id_owner_activo",
    "obtener_owner_activo",
    "solicitar_desvinculacion_propietario",
]
