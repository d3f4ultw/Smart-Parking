"""Controla la exclusividad y vigencia del editor de calibracion Vision."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import VisionCalibrationLease

DURACION_LEASE_SEGUNDOS = 30


class VisionCalibracionLeaseError(ValueError):
    """La instancia solicitante no posee un lease de calibracion vigente."""


def _ahora_base_datos(db: Session) -> datetime:
    """Usa el reloj de PostgreSQL para que todos los procesos comparen igual."""

    return cast(datetime, db.scalar(select(func.clock_timestamp())))


def _bloquear_lease(db: Session) -> VisionCalibrationLease:
    lease = db.scalar(
        select(VisionCalibrationLease)
        .where(VisionCalibrationLease.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if lease is None:
        raise RuntimeError("No existe la fila singleton del lease de calibracion.")
    return lease


def _lease_vigente(lease: VisionCalibrationLease, ahora: datetime) -> bool:
    return lease.expires_at is not None and lease.expires_at > ahora


def _limpiar(lease: VisionCalibrationLease) -> None:
    lease.owner_session_hash = None
    lease.editor_instance_id = None
    lease.expires_at = None


def _exigir_propietario(
    lease: VisionCalibrationLease,
    *,
    ahora: datetime,
    token_sesion_hash: str,
    editor_instance_id: UUID,
) -> None:
    if (
        not _lease_vigente(lease, ahora)
        or lease.owner_session_hash != token_sesion_hash
        or lease.editor_instance_id != editor_instance_id
    ):
        raise VisionCalibracionLeaseError(
            "El editor perdió el acceso exclusivo a la calibración."
        )


def consultar_disponibilidad(db: Session) -> bool:
    """Indica si no hay un propietario con lease vigente."""

    lease = db.get(VisionCalibrationLease, 1)
    ahora = _ahora_base_datos(db)
    return lease is None or not _lease_vigente(lease, ahora)


def adquirir_lease(
    db: Session,
    *,
    token_sesion_hash: str,
    editor_instance_id: UUID,
) -> None:
    """Adquiere el lease o renueva una adquisicion repetida de la misma instancia."""

    with db.begin():
        lease = _bloquear_lease(db)
        ahora = _ahora_base_datos(db)
        vigente = _lease_vigente(lease, ahora)
        es_misma_instancia = (
            lease.owner_session_hash == token_sesion_hash
            and lease.editor_instance_id == editor_instance_id
        )

        if vigente and not es_misma_instancia:
            raise VisionCalibracionLeaseError("Calibración en uso.")
        if not vigente and es_misma_instancia and lease.expires_at is not None:
            raise VisionCalibracionLeaseError(
                "El lease de esta instancia expiró. Cierra y vuelve a abrir el editor."
            )

        lease.owner_session_hash = token_sesion_hash
        lease.editor_instance_id = editor_instance_id
        lease.expires_at = ahora + timedelta(seconds=DURACION_LEASE_SEGUNDOS)


def renovar_lease(
    db: Session,
    *,
    token_sesion_hash: str,
    editor_instance_id: UUID,
) -> None:
    """Renueva solo si la misma sesion y ventana conservan el lease vigente."""

    with db.begin():
        lease = _bloquear_lease(db)
        ahora = _ahora_base_datos(db)
        _exigir_propietario(
            lease,
            ahora=ahora,
            token_sesion_hash=token_sesion_hash,
            editor_instance_id=editor_instance_id,
        )
        lease.expires_at = ahora + timedelta(seconds=DURACION_LEASE_SEGUNDOS)


def verificar_lease_en_transaccion(
    db: Session,
    *,
    token_sesion_hash: str,
    editor_instance_id: UUID,
) -> None:
    """Verifica el lease manteniendo bloqueada su fila durante la escritura."""

    lease = _bloquear_lease(db)
    ahora = _ahora_base_datos(db)
    _exigir_propietario(
        lease,
        ahora=ahora,
        token_sesion_hash=token_sesion_hash,
        editor_instance_id=editor_instance_id,
    )


def exigir_lease_libre_en_transaccion(db: Session) -> None:
    """Evita que el cliente interno de Vision cambie zonas durante una edicion OWNER."""

    lease = _bloquear_lease(db)
    ahora = _ahora_base_datos(db)
    if _lease_vigente(lease, ahora):
        raise VisionCalibracionLeaseError("Calibración en uso.")


def liberar_lease(
    db: Session,
    *,
    token_sesion_hash: str,
    editor_instance_id: UUID,
) -> bool:
    """Libera el lease si coincide con la sesion y la instancia solicitantes."""

    with db.begin():
        lease = _bloquear_lease(db)
        if (
            lease.owner_session_hash != token_sesion_hash
            or lease.editor_instance_id != editor_instance_id
        ):
            return False
        _limpiar(lease)
        return True


def liberar_lease_de_sesion(db: Session, *, token_sesion_hash: str) -> bool:
    """Retira de inmediato el lease cuando OWNER revoca su autorizacion Vision."""

    with db.begin():
        lease = _bloquear_lease(db)
        if lease.owner_session_hash != token_sesion_hash:
            return False
        _limpiar(lease)
        return True


__all__ = [
    "DURACION_LEASE_SEGUNDOS",
    "VisionCalibracionLeaseError",
    "adquirir_lease",
    "consultar_disponibilidad",
    "exigir_lease_libre_en_transaccion",
    "liberar_lease",
    "liberar_lease_de_sesion",
    "renovar_lease",
    "verificar_lease_en_transaccion",
]
