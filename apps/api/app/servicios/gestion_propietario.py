"""Gestiona el ticket web y la sesion temporal del primer OWNER."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.sesion_gestion_propietario import SesionGestionPropietario

VIGENCIA_ENLACE_GESTION_SEGUNDOS = 10 * 60
INTERVALO_LATIDO_SEGUNDOS = 15
GRACIA_LATIDO_SEGUNDOS = 60
MAXIMO_INTENTOS_APAREAMIENTO = 5
_CLAVE_BLOQUEO_GESTION = 5_704_609_864_030_912_339
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class SesionGestionPropietarioNoDisponible(ValueError):
    """Indica que el ticket o la sesion no pueden autorizar otra operacion."""


class CodigoApareamientoInvalido(ValueError):
    """Indica que el codigo no coincide con el ticket pendiente."""


@dataclass(frozen=True, slots=True)
class ResultadoEmisionGestion:
    """Resultado que entrega credenciales solo al proceso lanzador."""

    estado: Literal["emitida", "activa"]
    ticket: str | None = field(default=None, repr=False)
    codigo_apareamiento: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ResultadoReclamoGestion:
    """Resultado de asociar el ticket con una cookie de navegador."""

    id_sesion: int
    credencial_nueva: str | None = field(default=None, repr=False)


def _ahora_transaccion(db: Session, ahora: datetime | None) -> datetime:
    if ahora is not None:
        if ahora.tzinfo is None or ahora.utcoffset() is None:
            raise ValueError("La fecha de gestion debe incluir zona horaria.")
        return ahora.astimezone(UTC)
    valor = db.scalar(select(func.clock_timestamp()))
    if not isinstance(valor, datetime):
        raise SQLAlchemyError("No se pudo obtener la hora de PostgreSQL.")
    if valor.tzinfo is None or valor.utcoffset() is None:
        return valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC)


def _bloquear_gestion(db: Session) -> None:
    """Serializa emisión, reclamo y expiración entre procesos y workers."""

    db.execute(
        text("SELECT pg_advisory_xact_lock(:clave)"),
        {"clave": _CLAVE_BLOQUEO_GESTION},
    )


def _hash_credencial(proposito: str, valor: str) -> str:
    return hashlib.sha256(f"owner-web-v1:{proposito}:{valor}".encode()).hexdigest()


def _normalizar_codigo(codigo: str) -> str:
    return re.sub(r"[^A-Z2-9]", "", codigo.upper())


def _terminar_sesion(
    sesion: SesionGestionPropietario,
    *,
    estado: Literal["reemplazada", "expirada"],
    ahora: datetime,
) -> None:
    sesion.estado = estado
    sesion.ticket_hash = None
    sesion.codigo_apareamiento_hash = None
    sesion.credencial_hash = None
    sesion.terminada_en = ahora


def emitir_sesion_gestion(
    db: Session,
    *,
    ahora: datetime | None = None,
) -> ResultadoEmisionGestion:
    """Emite un URL pendiente o informa que ya hay un navegador autorizado."""

    ticket = secrets.token_urlsafe(32)
    codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(16))
    try:
        db.rollback()
        with db.begin():
            _bloquear_gestion(db)
            instante = _ahora_transaccion(db, ahora)
            sesion_actual = db.scalar(
                select(SesionGestionPropietario)
                .where(SesionGestionPropietario.estado.in_(("pendiente", "activa")))
                .order_by(SesionGestionPropietario.id.desc())
                .with_for_update()
            )
            if sesion_actual is not None:
                if sesion_actual.estado == "activa":
                    limite = instante - timedelta(seconds=GRACIA_LATIDO_SEGUNDOS)
                    if (
                        sesion_actual.ultimo_latido_en is not None
                        and sesion_actual.ultimo_latido_en > limite
                    ):
                        return ResultadoEmisionGestion(estado="activa")
                    _terminar_sesion(
                        sesion_actual,
                        estado="expirada",
                        ahora=instante,
                    )
                elif sesion_actual.preclaim_expira_en > instante:
                    _terminar_sesion(
                        sesion_actual,
                        estado="reemplazada",
                        ahora=instante,
                    )
                else:
                    _terminar_sesion(
                        sesion_actual,
                        estado="expirada",
                        ahora=instante,
                    )

            nueva_sesion = SesionGestionPropietario(
                estado="pendiente",
                ticket_hash=_hash_credencial("ticket", ticket),
                codigo_apareamiento_hash=_hash_credencial(
                    "apareamiento",
                    codigo,
                ),
                preclaim_expira_en=instante
                + timedelta(seconds=VIGENCIA_ENLACE_GESTION_SEGUNDOS),
            )
            db.add(nueva_sesion)
            db.flush()
    except IntegrityError:
        db.rollback()
        return ResultadoEmisionGestion(estado="activa")
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoEmisionGestion(
        estado="emitida",
        ticket=ticket,
        codigo_apareamiento=codigo,
    )


def reclamar_sesion_gestion(
    db: Session,
    *,
    ticket: str,
    codigo_apareamiento: str | None,
    credencial_actual: str | None,
    ahora: datetime | None = None,
) -> ResultadoReclamoGestion:
    """Vincula la primera pareja URL/codigo y permite reclamos idempotentes."""

    ticket_hash = _hash_credencial("ticket", ticket)
    credencial_hash = (
        _hash_credencial("sesion", credencial_actual) if credencial_actual else None
    )
    resultado: ResultadoReclamoGestion | None = None
    error: type[ValueError] | None = None
    try:
        db.rollback()
        with db.begin():
            _bloquear_gestion(db)
            instante = _ahora_transaccion(db, ahora)
            sesion = db.scalar(
                select(SesionGestionPropietario)
                .where(SesionGestionPropietario.ticket_hash == ticket_hash)
                .with_for_update()
            )
            if sesion is None:
                error = SesionGestionPropietarioNoDisponible
            elif sesion.estado == "activa":
                limite = instante - timedelta(seconds=GRACIA_LATIDO_SEGUNDOS)
                if (
                    credencial_hash is not None
                    and secrets.compare_digest(
                        sesion.credencial_hash or "",
                        credencial_hash,
                    )
                    and sesion.ultimo_latido_en is not None
                    and sesion.ultimo_latido_en > limite
                ):
                    sesion.ultimo_latido_en = instante
                    resultado = ResultadoReclamoGestion(id_sesion=sesion.id)
                else:
                    if (
                        sesion.ultimo_latido_en is None
                        or sesion.ultimo_latido_en <= limite
                    ):
                        _terminar_sesion(sesion, estado="expirada", ahora=instante)
                    error = SesionGestionPropietarioNoDisponible
            elif (
                sesion.estado != "pendiente"
                or sesion.preclaim_expira_en <= instante
                or sesion.codigo_apareamiento_hash is None
            ):
                if sesion.estado == "pendiente":
                    _terminar_sesion(sesion, estado="expirada", ahora=instante)
                error = SesionGestionPropietarioNoDisponible
            elif codigo_apareamiento is None:
                error = SesionGestionPropietarioNoDisponible
            else:
                codigo_normalizado = _normalizar_codigo(codigo_apareamiento)
                codigo_hash = _hash_credencial("apareamiento", codigo_normalizado)
                if not secrets.compare_digest(
                    sesion.codigo_apareamiento_hash,
                    codigo_hash,
                ):
                    sesion.intentos_apareamiento += 1
                    if sesion.intentos_apareamiento >= MAXIMO_INTENTOS_APAREAMIENTO:
                        _terminar_sesion(sesion, estado="expirada", ahora=instante)
                    error = CodigoApareamientoInvalido
                else:
                    credencial = secrets.token_urlsafe(32)
                    sesion.estado = "activa"
                    sesion.codigo_apareamiento_hash = None
                    sesion.credencial_hash = _hash_credencial("sesion", credencial)
                    sesion.reclamada_en = instante
                    sesion.ultimo_latido_en = instante
                    resultado = ResultadoReclamoGestion(
                        id_sesion=sesion.id,
                        credencial_nueva=credencial,
                    )
    except SQLAlchemyError:
        db.rollback()
        raise

    if error is not None:
        raise error
    if resultado is None:
        raise SesionGestionPropietarioNoDisponible
    return resultado


def renovar_sesion_gestion(
    db: Session,
    *,
    credencial: str,
    ahora: datetime | None = None,
) -> bool:
    """Registra un latido si la cookie aún pertenece al lease activo."""

    credencial_hash = _hash_credencial("sesion", credencial)
    activa = False
    try:
        db.rollback()
        with db.begin():
            sesion = db.scalar(
                select(SesionGestionPropietario)
                .where(
                    SesionGestionPropietario.estado == "activa",
                    SesionGestionPropietario.credencial_hash == credencial_hash,
                )
                .with_for_update()
            )
            instante = _ahora_transaccion(db, ahora)
            if sesion is not None:
                limite = instante - timedelta(seconds=GRACIA_LATIDO_SEGUNDOS)
                if (
                    sesion.ultimo_latido_en is not None
                    and sesion.ultimo_latido_en > limite
                ):
                    sesion.ultimo_latido_en = instante
                    activa = True
                else:
                    _terminar_sesion(sesion, estado="expirada", ahora=instante)
    except SQLAlchemyError:
        db.rollback()
        raise
    return activa


def validar_sesion_gestion(
    db: Session,
    *,
    credencial: str | None,
    ahora: datetime | None = None,
) -> int | None:
    """Devuelve el identificador autorizado y expira leases fuera de ventana."""

    if not credencial:
        db.rollback()
        return None
    credencial_hash = _hash_credencial("sesion", credencial)
    id_sesion: int | None = None
    try:
        db.rollback()
        with db.begin():
            sesion = db.scalar(
                select(SesionGestionPropietario)
                .where(
                    SesionGestionPropietario.estado == "activa",
                    SesionGestionPropietario.credencial_hash == credencial_hash,
                )
                .with_for_update()
            )
            instante = _ahora_transaccion(db, ahora)
            if sesion is not None:
                limite = instante - timedelta(seconds=GRACIA_LATIDO_SEGUNDOS)
                if (
                    sesion.ultimo_latido_en is not None
                    and sesion.ultimo_latido_en > limite
                ):
                    id_sesion = sesion.id
                else:
                    _terminar_sesion(sesion, estado="expirada", ahora=instante)
    except SQLAlchemyError:
        db.rollback()
        raise
    return id_sesion


__all__ = [
    "GRACIA_LATIDO_SEGUNDOS",
    "INTERVALO_LATIDO_SEGUNDOS",
    "MAXIMO_INTENTOS_APAREAMIENTO",
    "VIGENCIA_ENLACE_GESTION_SEGUNDOS",
    "CodigoApareamientoInvalido",
    "ResultadoEmisionGestion",
    "ResultadoReclamoGestion",
    "SesionGestionPropietarioNoDisponible",
    "emitir_sesion_gestion",
    "reclamar_sesion_gestion",
    "renovar_sesion_gestion",
    "validar_sesion_gestion",
]
