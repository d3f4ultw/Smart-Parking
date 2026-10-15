"""Consultas y mutaciones transaccionales para cajones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cajon import (
    Cajon,
    EstadoEfectivoCajon,
    EstadoFisicoCajon,
    EstadoOperativoCajon,
)
from app.models.vision_configuration import VisionConfiguration
from app.servicios.eventos_operadores import registrar_evento_cajon

UMBRAL_DESACTUALIZACION_SEGUNDOS = 45


class CajonNoEncontradoError(LookupError):
    """Indica que el identificador no corresponde a un cajon persistido."""


class DatosOperativosCajonInvalidosError(ValueError):
    """Indica que la combinacion operativa y motivo no es valida."""


@dataclass(frozen=True, slots=True)
class CajonDTO:
    """Campos seguros para APIs de personal."""

    id: int
    numero: int
    vision_zone_id: UUID
    activa: bool
    estado_fisico: EstadoFisicoCajon
    estado_operativo: EstadoOperativoCajon
    motivo_operativo: str | None
    estado_fisico_actualizado_en: datetime | None
    estado_operativo_actualizado_en: datetime
    creado_en: datetime
    estado_efectivo: EstadoEfectivoCajon
    vision_desactualizada: bool


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


def _vision_desactualizada(db: Session, ahora: datetime) -> bool:
    configuracion = db.get(VisionConfiguration, 1)
    return (
        configuracion is None
        or configuracion.last_observation_at is None
        or (ahora - configuracion.last_observation_at).total_seconds()
        > UMBRAL_DESACTUALIZACION_SEGUNDOS
    )


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


def _crear_dto(cajon: Cajon, *, vision_desactualizada: bool = False) -> CajonDTO:
    estado_efectivo = obtener_estado_efectivo(cajon)
    if vision_desactualizada and estado_efectivo in {
        EstadoEfectivoCajon.LIBRE,
        EstadoEfectivoCajon.OCUPADO,
    }:
        estado_efectivo = EstadoEfectivoCajon.DESCONOCIDO
    return CajonDTO(
        id=cajon.id,
        numero=cajon.numero,
        vision_zone_id=cajon.vision_zone_id,
        activa=cajon.activa,
        estado_fisico=(
            EstadoFisicoCajon.DESCONOCIDO
            if vision_desactualizada
            else EstadoFisicoCajon(cajon.estado_fisico)
        ),
        estado_operativo=EstadoOperativoCajon(cajon.estado_operativo),
        motivo_operativo=cajon.motivo_operativo,
        estado_fisico_actualizado_en=cajon.estado_fisico_actualizado_en,
        estado_operativo_actualizado_en=cajon.estado_operativo_actualizado_en,
        creado_en=cajon.creado_en,
        estado_efectivo=estado_efectivo,
        vision_desactualizada=vision_desactualizada,
    )


def _crear_instantanea_evento(
    cajon: Cajon,
    *,
    actualizado_en: datetime,
    vision_desactualizada: bool = False,
) -> dict[str, object]:
    return {
        "cajon_id": cajon.id,
        "numero": cajon.numero,
        "vision_zone_id": str(cajon.vision_zone_id),
        "activa": cajon.activa,
        "vision_desactualizada": vision_desactualizada,
        "estado_fisico": _crear_dto(
            cajon,
            vision_desactualizada=vision_desactualizada,
        ).estado_fisico.value,
        "estado_operativo": cajon.estado_operativo,
        "motivo_operativo": cajon.motivo_operativo,
        "estado_efectivo": _crear_dto(
            cajon,
            vision_desactualizada=vision_desactualizada,
        ).estado_efectivo.value,
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


def crear_instantanea_evento_vision(
    cajon: Cajon,
    *,
    actualizado_en: datetime,
    vision_desactualizada: bool = False,
) -> dict[str, object]:
    """Serializa una zona para el contrato estricto de eventos del dashboard."""

    return _crear_instantanea_evento(
        cajon,
        actualizado_en=actualizado_en,
        vision_desactualizada=vision_desactualizada,
    )


def listar_cajones(
    db: Session,
    *,
    vision_desactualizada: bool = False,
) -> list[CajonDTO]:
    """Lista solo zonas activas en orden numerico."""

    cajones = db.scalars(
        select(Cajon).where(Cajon.activa.is_(True)).order_by(Cajon.numero)
    ).all()
    return [
        _crear_dto(cajon, vision_desactualizada=vision_desactualizada)
        for cajon in cajones
    ]


def _bloquear_cajon(db: Session, cajon_id: int) -> Cajon:
    cajon = db.scalar(
        select(Cajon)
        .where(Cajon.id == cajon_id, Cajon.activa.is_(True))
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
    motivo_normalizado = (motivo.strip() or None) if motivo is not None else None
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
                return ResultadoMutacionCajon(
                    _crear_dto(
                        cajon,
                        vision_desactualizada=_vision_desactualizada(
                            db,
                            _ahora_utc(ahora),
                        ),
                    ),
                    False,
                )

            fecha_cambio = _ahora_utc(ahora)
            cajon.estado_operativo = nuevo_estado.value
            cajon.motivo_operativo = motivo_normalizado
            cajon.estado_operativo_actualizado_en = fecha_cambio
            db.flush()
            desactualizada = _vision_desactualizada(db, fecha_cambio)
            registrar_evento_cajon(
                db,
                cajon.id,
                _crear_instantanea_evento(
                    cajon,
                    actualizado_en=fecha_cambio,
                    vision_desactualizada=desactualizada,
                ),
            )
            return ResultadoMutacionCajon(
                _crear_dto(
                    cajon,
                    vision_desactualizada=desactualizada,
                ),
                True,
            )
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "CajonDTO",
    "CajonNoEncontradoError",
    "DatosOperativosCajonInvalidosError",
    "ResultadoMutacionCajon",
    "UMBRAL_DESACTUALIZACION_SEGUNDOS",
    "cambiar_estado_operativo",
    "crear_instantanea_evento_vision",
    "listar_cajones",
    "obtener_estado_efectivo",
]
