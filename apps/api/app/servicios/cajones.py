"""Consultas y mutaciones transaccionales para cajones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cajon import (
    Cajon,
    EstadoEfectivoCajon,
    EstadoFisicoCajon,
    EstadoOperativoCajon,
)
from app.servicios.eventos_operadores import registrar_evento_cajon


class CajonNoEncontradoError(LookupError):
    """Indica que el identificador no corresponde a un cajon persistido."""


class DatosOperativosCajonInvalidosError(ValueError):
    """Indica que la combinacion operativa y motivo no es valida."""


@dataclass(frozen=True, slots=True)
class CajonDTO:
    """Campos seguros para APIs de personal."""

    id: int
    numero: int
    estado_fisico: EstadoFisicoCajon
    estado_operativo: EstadoOperativoCajon
    motivo_operativo: str | None
    estado_fisico_actualizado_en: datetime | None
    estado_operativo_actualizado_en: datetime
    creado_en: datetime
    estado_efectivo: EstadoEfectivoCajon


@dataclass(frozen=True, slots=True)
class ResultadoMutacionCajon:
    """Instantanea actual y si una mutacion real fue aplicada."""

    cajon: CajonDTO
    cambio_aplicado: bool


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha del cambio debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def obtener_estado_efectivo(cajon: Cajon) -> EstadoEfectivoCajon:
    """Deriva la disponibilidad priorizando el bloqueo operativo."""

    estado_operativo = EstadoOperativoCajon(cajon.estado_operativo)
    if estado_operativo != EstadoOperativoCajon.DISPONIBLE:
        return EstadoEfectivoCajon.NO_DISPONIBLE

    estado_fisico = EstadoFisicoCajon(cajon.estado_fisico)
    if estado_fisico == EstadoFisicoCajon.OCUPADO:
        return EstadoEfectivoCajon.OCUPADO
    if estado_fisico == EstadoFisicoCajon.LIBRE:
        return EstadoEfectivoCajon.LIBRE
    return EstadoEfectivoCajon.DESCONOCIDO


def _crear_dto(cajon: Cajon) -> CajonDTO:
    return CajonDTO(
        id=cajon.id,
        numero=cajon.numero,
        estado_fisico=EstadoFisicoCajon(cajon.estado_fisico),
        estado_operativo=EstadoOperativoCajon(cajon.estado_operativo),
        motivo_operativo=cajon.motivo_operativo,
        estado_fisico_actualizado_en=cajon.estado_fisico_actualizado_en,
        estado_operativo_actualizado_en=cajon.estado_operativo_actualizado_en,
        creado_en=cajon.creado_en,
        estado_efectivo=obtener_estado_efectivo(cajon),
    )


def _crear_instantanea_evento(
    cajon: Cajon,
    *,
    actualizado_en: datetime,
) -> dict[str, object]:
    return {
        "cajon_id": cajon.id,
        "numero": cajon.numero,
        "estado_fisico": cajon.estado_fisico,
        "estado_operativo": cajon.estado_operativo,
        "motivo_operativo": cajon.motivo_operativo,
        "estado_efectivo": obtener_estado_efectivo(cajon).value,
        "estado_fisico_actualizado_en": (
            cajon.estado_fisico_actualizado_en.isoformat()
            if cajon.estado_fisico_actualizado_en is not None
            else None
        ),
        "estado_operativo_actualizado_en": (
            cajon.estado_operativo_actualizado_en.isoformat()
        ),
        "actualizado_en": actualizado_en.isoformat(),
    }


def listar_cajones(db: Session) -> list[CajonDTO]:
    """Lista todos los cajones en orden numerico."""

    cajones = db.scalars(select(Cajon).order_by(Cajon.numero)).all()
    return [_crear_dto(cajon) for cajon in cajones]


def _bloquear_cajon(db: Session, cajon_id: int) -> Cajon:
    cajon = db.scalar(
        select(Cajon)
        .where(Cajon.id == cajon_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if cajon is None:
        raise CajonNoEncontradoError
    return cajon


def cambiar_estado_operativo(
    db: Session,
    cajon_id: int,
    *,
    estado: EstadoOperativoCajon | str,
    motivo: str | None,
    ahora: datetime | None = None,
) -> ResultadoMutacionCajon:
    """Actualiza solo la dimension operativa y registra su evento atomico."""

    nuevo_estado = EstadoOperativoCajon(estado)
    motivo_normalizado = (
        (motivo.strip() or None) if motivo is not None else None
    )
    if motivo_normalizado is not None and len(motivo_normalizado) > 250:
        raise DatosOperativosCajonInvalidosError
    if nuevo_estado == EstadoOperativoCajon.DISPONIBLE:
        if motivo_normalizado is not None:
            raise DatosOperativosCajonInvalidosError

    try:
        with db.begin():
            cajon = _bloquear_cajon(db, cajon_id)
            if (
                cajon.estado_operativo == nuevo_estado.value
                and cajon.motivo_operativo == motivo_normalizado
            ):
                return ResultadoMutacionCajon(_crear_dto(cajon), False)

            fecha_cambio = _ahora_utc(ahora)
            cajon.estado_operativo = nuevo_estado.value
            cajon.motivo_operativo = motivo_normalizado
            cajon.estado_operativo_actualizado_en = fecha_cambio
            db.flush()
            registrar_evento_cajon(
                db,
                cajon.id,
                _crear_instantanea_evento(cajon, actualizado_en=fecha_cambio),
            )
            return ResultadoMutacionCajon(_crear_dto(cajon), True)
    except SQLAlchemyError:
        db.rollback()
        raise


def cambiar_estado_fisico(
    db: Session,
    cajon_id: int,
    *,
    ocupado: bool,
    ahora: datetime | None = None,
) -> ResultadoMutacionCajon:
    """Aplica solo el estado reportado por el dispositivo y su evento."""

    nuevo_estado = EstadoFisicoCajon.OCUPADO if ocupado else EstadoFisicoCajon.LIBRE
    try:
        with db.begin():
            cajon = _bloquear_cajon(db, cajon_id)
            if cajon.estado_fisico == nuevo_estado.value:
                return ResultadoMutacionCajon(_crear_dto(cajon), False)

            fecha_cambio = _ahora_utc(ahora)
            cajon.estado_fisico = nuevo_estado.value
            cajon.estado_fisico_actualizado_en = fecha_cambio
            db.flush()
            registrar_evento_cajon(
                db,
                cajon.id,
                _crear_instantanea_evento(cajon, actualizado_en=fecha_cambio),
            )
            return ResultadoMutacionCajon(_crear_dto(cajon), True)
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "CajonDTO",
    "CajonNoEncontradoError",
    "DatosOperativosCajonInvalidosError",
    "ResultadoMutacionCajon",
    "cambiar_estado_fisico",
    "cambiar_estado_operativo",
    "listar_cajones",
    "obtener_estado_efectivo",
]
