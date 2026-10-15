"""Reglas transaccionales para configuracion y telemetria de Vision."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.esquemas.vision import (
    RespuestaAceptacionVision,
    RespuestaConfiguracionVision,
    RespuestaSesionVision,
    SolicitudConfiguracionVision,
    SolicitudObservacionesVision,
    SolicitudSecuenciaVision,
    ZonaVision,
)
from app.models import Cajon, VisionConfiguration, VisionRequest
from app.servicios.cajones import crear_instantanea_evento_vision
from app.servicios.eventos_operadores import registrar_evento_cajon

UMBRAL_DESACTUALIZACION_SEGUNDOS = 45


class VisionConflictoError(ValueError):
    """Indica una revision, sesion o secuencia que ya no es vigente."""


class VisionConfiguracionError(ValueError):
    """Indica una instantanea de calibracion que viola el contrato."""


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _configuracion_bloqueada(db: Session) -> VisionConfiguration:
    configuracion = db.scalar(
        select(VisionConfiguration)
        .where(VisionConfiguration.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if configuracion is None:
        raise RuntimeError("No existe la configuracion singleton de Vision.")
    return configuracion


def _normalizar_poligono(zona: ZonaVision) -> list[list[float]]:
    puntos = [[float(x), float(y)] for x, y in zona.polygon]
    if len(puntos) < 3 or len(puntos) > 128:
        raise VisionConfiguracionError("El poligono debe tener entre 3 y 128 vertices.")
    if len({(punto[0], punto[1]) for punto in puntos}) < 3 or any(
        punto == puntos[(indice + 1) % len(puntos)]
        for indice, punto in enumerate(puntos)
    ):
        raise VisionConfiguracionError("El poligono requiere vertices distintos.")

    area_doble = sum(
        puntos[indice][0] * puntos[(indice + 1) % len(puntos)][1]
        - puntos[(indice + 1) % len(puntos)][0] * puntos[indice][1]
        for indice in range(len(puntos))
    )
    if not math.isfinite(area_doble) or abs(area_doble) < 1e-8:
        raise VisionConfiguracionError("El poligono no puede tener area nula.")

    def orientacion(a: list[float], b: list[float], c: list[float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def esta_en_segmento(a: list[float], b: list[float], p: list[float]) -> bool:
        return (
            min(a[0], b[0]) - 1e-12 <= p[0] <= max(a[0], b[0]) + 1e-12
            and min(a[1], b[1]) - 1e-12 <= p[1] <= max(a[1], b[1]) + 1e-12
        )

    def se_intersectan(
        a: list[float], b: list[float], c: list[float], d: list[float]
    ) -> bool:
        o1, o2 = orientacion(a, b, c), orientacion(a, b, d)
        o3, o4 = orientacion(c, d, a), orientacion(c, d, b)
        if o1 * o2 < 0 and o3 * o4 < 0:
            return True
        return any(
            abs(origen) <= 1e-12 and esta_en_segmento(inicio, fin, punto)
            for origen, inicio, fin, punto in (
                (o1, a, b, c),
                (o2, a, b, d),
                (o3, c, d, a),
                (o4, c, d, b),
            )
        )

    cantidad = len(puntos)
    for indice_a in range(cantidad):
        a1 = puntos[indice_a]
        a2 = puntos[(indice_a + 1) % cantidad]
        for indice_b in range(indice_a + 1, cantidad):
            if indice_b in {indice_a, (indice_a + 1) % cantidad}:
                continue
            if (indice_b + 1) % cantidad == indice_a:
                continue
            b1 = puntos[indice_b]
            b2 = puntos[(indice_b + 1) % cantidad]
            if se_intersectan(a1, a2, b1, b2):
                raise VisionConfiguracionError(
                    "El poligono no puede cruzarse a si mismo."
                )
    return puntos


def _digest(payload: object) -> str:
    serializado = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def _obtener_reintento(
    db: Session,
    *,
    request_id: UUID,
    request_type: str,
    request_digest: str,
) -> dict[str, Any] | None:
    anterior = db.get(VisionRequest, request_id)
    if anterior is None:
        return None
    if (
        anterior.request_type != request_type
        or anterior.request_digest != request_digest
    ):
        raise VisionConflictoError("El identificador de solicitud ya fue utilizado.")
    return anterior.response


def _guardar_reintento(
    db: Session,
    *,
    request_id: UUID,
    request_type: str,
    request_digest: str,
    response: dict[str, Any],
) -> None:
    db.add(
        VisionRequest(
            request_id=request_id,
            request_type=request_type,
            request_digest=request_digest,
            response=response,
        )
    )
    db.flush()


def _respuesta_configuracion(
    db: Session,
    configuracion: VisionConfiguration,
) -> dict[str, Any]:
    zonas = db.scalars(
        select(Cajon).where(Cajon.activa.is_(True)).order_by(Cajon.numero)
    ).all()
    return RespuestaConfiguracionVision(
        revision=configuracion.revision,
        next_c_number=configuracion.next_c_number,
        zones=[
            {
                "vision_zone_id": cajon.vision_zone_id,
                "numero": cajon.numero,
                "cajon_id": cajon.id,
                "polygon": cajon.poligono,
            }
            for cajon in zonas
        ],
    ).model_dump(mode="json")


def cargar_configuracion_vision(db: Session) -> dict[str, Any]:
    configuracion = _configuracion_bloqueada(db)
    return _respuesta_configuracion(db, configuracion)


def guardar_configuracion_vision(
    db: Session,
    solicitud: SolicitudConfiguracionVision,
) -> dict[str, Any]:
    cuerpo = solicitud.model_dump(mode="json")
    digest = _digest(cuerpo)
    ahora = _ahora_utc()

    with db.begin():
        configuracion = _configuracion_bloqueada(db)
        reintento = _obtener_reintento(
            db,
            request_id=solicitud.request_id,
            request_type="configuration",
            request_digest=digest,
        )
        if reintento is not None:
            return reintento
        if configuracion.revision != solicitud.expected_revision:
            raise VisionConflictoError(
                "La revision de calibracion cambio; vuelve a cargarla."
            )

        anteriores = db.scalars(
            select(Cajon).with_for_update().execution_options(populate_existing=True)
        ).all()
        por_id = {cajon.vision_zone_id: cajon for cajon in anteriores}
        ids_solicitados = {zona.vision_zone_id for zona in solicitud.zones}
        cambios: list[Cajon] = []

        for zona in solicitud.zones:
            poligono = _normalizar_poligono(zona)
            cajon = por_id.get(zona.vision_zone_id)
            if cajon is None:
                if zona.numero is not None:
                    raise VisionConfiguracionError(
                        "Una zona nueva no puede elegir su numero permanente."
                    )
                cajon = Cajon(
                    numero=configuracion.next_c_number,
                    vision_zone_id=zona.vision_zone_id,
                    poligono=poligono,
                    activa=True,
                    estado_fisico="DESCONOCIDO",
                )
                configuracion.next_c_number += 1
                db.add(cajon)
                db.flush()
                cambios.append(cajon)
                continue

            if not cajon.activa:
                raise VisionConfiguracionError(
                    "Una zona retirada no puede reactivarse."
                )
            if zona.numero != cajon.numero:
                raise VisionConfiguracionError(
                    "El numero de una zona existente es inmutable."
                )
            if cajon.poligono != poligono:
                cajon.poligono = poligono
                cajon.estado_fisico = "DESCONOCIDO"
                cajon.estado_fisico_actualizado_en = None
                cambios.append(cajon)

        for cajon in anteriores:
            if cajon.activa and cajon.vision_zone_id not in ids_solicitados:
                cajon.activa = False
                cambios.append(cajon)

        configuracion.revision += 1
        configuracion.current_session_id = None
        configuracion.last_sequence = 0
        configuracion.last_heartbeat_at = None
        configuracion.last_observation_at = None
        db.flush()

        for cajon in cambios:
            registrar_evento_cajon(
                db,
                cajon.id,
                crear_instantanea_evento_vision(
                    cajon,
                    actualizado_en=ahora,
                    vision_desactualizada=True,
                ),
            )

        respuesta = _respuesta_configuracion(db, configuracion)
        _guardar_reintento(
            db,
            request_id=solicitud.request_id,
            request_type="configuration",
            request_digest=digest,
            response=respuesta,
        )
        return respuesta


def iniciar_sesion_vision(db: Session) -> dict[str, Any]:
    with db.begin():
        configuracion = _configuracion_bloqueada(db)
        sesion = uuid4()
        configuracion.current_session_id = sesion
        configuracion.last_sequence = 0
        configuracion.last_heartbeat_at = _ahora_utc()
        configuracion.last_observation_at = None
        return RespuestaSesionVision(
            session_id=sesion,
            revision=configuracion.revision,
        ).model_dump(mode="json")


def _aceptar_secuencia(
    db: Session,
    solicitud: SolicitudSecuenciaVision,
    *,
    request_type: str,
    revision: int | None,
    aceptar: Callable[[Session, VisionConfiguration], int],
) -> dict[str, Any]:
    digest = _digest(solicitud.model_dump(mode="json"))
    with db.begin():
        configuracion = _configuracion_bloqueada(db)
        reintento = _obtener_reintento(
            db,
            request_id=solicitud.request_id,
            request_type=request_type,
            request_digest=digest,
        )
        if reintento is not None:
            return reintento
        if configuracion.current_session_id != solicitud.session_id:
            raise VisionConflictoError("La sesion Vision ya no es vigente.")
        if revision is not None and revision != configuracion.revision:
            raise VisionConflictoError("La revision de calibracion cambio.")
        if solicitud.sequence <= configuracion.last_sequence:
            raise VisionConflictoError(
                "La secuencia debe ser mayor a la ultima aceptada."
            )

        cambiado = aceptar(db, configuracion)
        configuracion.last_sequence = solicitud.sequence
        configuracion.last_heartbeat_at = _ahora_utc()
        respuesta = RespuestaAceptacionVision(
            accepted=True,
            revision=configuracion.revision,
            sequence=solicitud.sequence,
            changed_slots=cambiado,
        ).model_dump(mode="json")
        _guardar_reintento(
            db,
            request_id=solicitud.request_id,
            request_type=request_type,
            request_digest=digest,
            response=respuesta,
        )
        return respuesta


def recibir_heartbeat_vision(
    db: Session,
    solicitud: SolicitudSecuenciaVision,
) -> dict[str, Any]:
    return _aceptar_secuencia(
        db,
        solicitud,
        request_type="heartbeat",
        revision=None,
        aceptar=lambda _db, _config: 0,
    )


def recibir_observaciones_vision(
    db: Session,
    solicitud: SolicitudObservacionesVision,
) -> dict[str, Any]:
    def aplicar(db_transaccion: Session, configuracion: VisionConfiguration) -> int:
        zonas = db_transaccion.scalars(
            select(Cajon)
            .where(Cajon.activa.is_(True))
            .order_by(Cajon.numero)
            .with_for_update()
        ).all()
        observaciones = {item.vision_zone_id: item for item in solicitud.observations}
        if set(observaciones) != {zona.vision_zone_id for zona in zonas}:
            raise VisionConfiguracionError(
                "La instantanea debe incluir cada zona activa exactamente una vez."
            )
        ahora = _ahora_utc()
        cambiados = 0
        for cajon in zonas:
            observacion = observaciones[cajon.vision_zone_id]
            if observacion.numero != cajon.numero:
                raise VisionConfiguracionError(
                    "El numero observado no coincide con Vision."
                )
            if cajon.estado_fisico != observacion.estado.value:
                cajon.estado_fisico = observacion.estado.value
                cajon.estado_fisico_actualizado_en = ahora
                db_transaccion.flush()
                registrar_evento_cajon(
                    db_transaccion,
                    cajon.id,
                    crear_instantanea_evento_vision(cajon, actualizado_en=ahora),
                )
                cambiados += 1
        configuracion.last_observation_at = ahora
        return cambiados

    return _aceptar_secuencia(
        db,
        solicitud,
        request_type="observations",
        revision=solicitud.revision,
        aceptar=aplicar,
    )


def obtener_estado_vision(
    db: Session, *, ahora: datetime | None = None
) -> dict[str, Any]:
    configuracion = db.get(VisionConfiguration, 1)
    if configuracion is None:
        raise RuntimeError("No existe la configuracion singleton de Vision.")
    momento = ahora or _ahora_utc()
    ultima = configuracion.last_observation_at
    desactualizada = (
        ultima is None
        or (momento - ultima).total_seconds() > UMBRAL_DESACTUALIZACION_SEGUNDOS
    )
    return {
        "stale": desactualizada,
        "last_heartbeat_at": (
            configuracion.last_heartbeat_at.isoformat()
            if configuracion.last_heartbeat_at is not None
            else None
        ),
        "last_observation_at": ultima.isoformat() if ultima is not None else None,
        "stale_after_seconds": UMBRAL_DESACTUALIZACION_SEGUNDOS,
    }


__all__ = [
    "UMBRAL_DESACTUALIZACION_SEGUNDOS",
    "VisionConfiguracionError",
    "VisionConflictoError",
    "cargar_configuracion_vision",
    "guardar_configuracion_vision",
    "iniciar_sesion_vision",
    "obtener_estado_vision",
    "recibir_heartbeat_vision",
    "recibir_observaciones_vision",
]
