"""Lectura y cambios atomicos de la modalidad de estacionamiento."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import ConfiguracionEstacionamiento, HistorialModalidadEstacionamiento

ModalidadEstacionamiento = Literal["PRIVADO", "PUBLICO", "MIXTO"]
MODALIDADES_ESTACIONAMIENTO = frozenset({"PRIVADO", "PUBLICO", "MIXTO"})
LIMITE_HISTORIAL_MODALIDAD = 20


class ModalidadEstacionamientoInvalidaError(ValueError):
    """Indica que la modalidad no pertenece al catalogo soportado."""


@dataclass(frozen=True, slots=True)
class ConfiguracionEstacionamientoDTO:
    """Estado vigente de la configuracion, apto para mostrar en la CLI."""

    modalidad: ModalidadEstacionamiento
    revision: int
    actualizado_en: datetime


@dataclass(frozen=True, slots=True)
class HistorialModalidadDTO:
    """Cambio de modalidad sin datos de identidad del operador."""

    modalidad_anterior: ModalidadEstacionamiento | None
    modalidad_nueva: ModalidadEstacionamiento
    cambiado_en: datetime


@dataclass(frozen=True, slots=True)
class ResultadoCambioModalidad:
    """Resultado persistido de una solicitud confirmada."""

    configuracion: ConfiguracionEstacionamientoDTO
    modalidad_anterior: ModalidadEstacionamiento | None
    cambio_realizado: bool


class ConfiguracionDesactualizadaError(RuntimeError):
    """Indica que otra CLI cambio la modalidad durante la confirmacion."""

    def __init__(
        self,
        configuracion_actual: ConfiguracionEstacionamientoDTO | None,
    ) -> None:
        self.configuracion_actual = configuracion_actual
        super().__init__("La configuracion cambio durante la confirmacion.")


def _crear_configuracion_dto(
    configuracion: ConfiguracionEstacionamiento,
) -> ConfiguracionEstacionamientoDTO:
    return ConfiguracionEstacionamientoDTO(
        modalidad=configuracion.modalidad,  # type: ignore[arg-type]
        revision=configuracion.revision,
        actualizado_en=configuracion.actualizado_en,
    )


def obtener_configuracion_estacionamiento(
    db: Session,
) -> ConfiguracionEstacionamientoDTO | None:
    """Lee la modalidad actual sin crear un valor por defecto."""

    configuracion = db.get(ConfiguracionEstacionamiento, 1)
    if configuracion is None:
        return None
    return _crear_configuracion_dto(configuracion)


def listar_historial_modalidad(
    db: Session,
    *,
    limite: int = LIMITE_HISTORIAL_MODALIDAD,
) -> list[HistorialModalidadDTO]:
    """Devuelve como maximo veinte cambios, del mas reciente al mas antiguo."""

    limite_efectivo = min(max(limite, 1), LIMITE_HISTORIAL_MODALIDAD)
    consulta = (
        select(HistorialModalidadEstacionamiento)
        .order_by(
            desc(HistorialModalidadEstacionamiento.revision),
            desc(HistorialModalidadEstacionamiento.id),
        )
        .limit(limite_efectivo)
    )
    return [
        HistorialModalidadDTO(
            modalidad_anterior=fila.modalidad_anterior,  # type: ignore[arg-type]
            modalidad_nueva=fila.modalidad_nueva,  # type: ignore[arg-type]
            cambiado_en=fila.cambiado_en,
        )
        for fila in db.scalars(consulta).all()
    ]


def _validar_modalidad(modalidad: str) -> ModalidadEstacionamiento:
    if modalidad not in MODALIDADES_ESTACIONAMIENTO:
        raise ModalidadEstacionamientoInvalidaError(
            "Selecciona PRIVADO, PUBLICO o MIXTO."
        )
    return modalidad  # type: ignore[return-value]


def cambiar_modalidad_estacionamiento(
    db: Session,
    modalidad: str,
    *,
    revision_esperada: int,
) -> ResultadoCambioModalidad:
    """Persiste una modalidad y su historial en una sola transaccion."""

    modalidad_validada = _validar_modalidad(modalidad)
    if type(revision_esperada) is not int or revision_esperada < 0:
        raise ValueError("La revision esperada debe ser un entero no negativo.")

    try:
        # La CLI no comparte escrituras pendientes con la consulta previa.
        db.rollback()
        with db.begin():
            if revision_esperada == 0:
                insercion = (
                    insert(ConfiguracionEstacionamiento)
                    .values(id=1, modalidad=modalidad_validada, revision=1)
                    .on_conflict_do_nothing(
                        index_elements=[ConfiguracionEstacionamiento.id]
                    )
                    .returning(ConfiguracionEstacionamiento.id)
                )
                id_insertado = db.scalar(insercion)
                if id_insertado is not None:
                    configuracion = db.get(ConfiguracionEstacionamiento, 1)
                    if configuracion is None:
                        raise RuntimeError("No se pudo leer la configuracion creada.")
                    db.add(
                        HistorialModalidadEstacionamiento(
                            configuracion_id=1,
                            revision=1,
                            modalidad_anterior=None,
                            modalidad_nueva=modalidad_validada,
                        )
                    )
                    db.flush()
                    db.refresh(configuracion)
                    resultado = ResultadoCambioModalidad(
                        configuracion=_crear_configuracion_dto(configuracion),
                        modalidad_anterior=None,
                        cambio_realizado=True,
                    )
                    return resultado

            configuracion = db.scalar(
                select(ConfiguracionEstacionamiento)
                .where(ConfiguracionEstacionamiento.id == 1)
                .with_for_update()
            )
            if configuracion is None or configuracion.revision != revision_esperada:
                estado_actual = (
                    _crear_configuracion_dto(configuracion)
                    if configuracion is not None
                    else None
                )
                raise ConfiguracionDesactualizadaError(estado_actual)

            modalidad_anterior = _validar_modalidad(configuracion.modalidad)
            if modalidad_anterior == modalidad_validada:
                return ResultadoCambioModalidad(
                    configuracion=_crear_configuracion_dto(configuracion),
                    modalidad_anterior=modalidad_anterior,
                    cambio_realizado=False,
                )

            nueva_revision = configuracion.revision + 1
            configuracion.modalidad = modalidad_validada
            configuracion.revision = nueva_revision
            configuracion.actualizado_en = func.now()
            db.add(
                HistorialModalidadEstacionamiento(
                    configuracion_id=1,
                    revision=nueva_revision,
                    modalidad_anterior=modalidad_anterior,
                    modalidad_nueva=modalidad_validada,
                )
            )
            db.flush()
            db.refresh(configuracion)
            return ResultadoCambioModalidad(
                configuracion=_crear_configuracion_dto(configuracion),
                modalidad_anterior=modalidad_anterior,
                cambio_realizado=True,
            )
    except SQLAlchemyError:
        db.rollback()
        raise
